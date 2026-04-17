"""Tests for StdinResponder.

The StdinResponder prompts on stdout with a format that discloses the
agent identity and turn position, and reads a single line from stdin
as the answer. An internal ``asyncio.Lock`` serializes concurrent
``respond`` calls; queued prompts surface queue depth so humans know
how many requests are stacked behind the current one.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import Iterator

import pytest

from agent_foundry.responders.models import (
    ClarificationRequest,
    PermissionRequest,
    ResponderContext,
    ResponderResponse,
)
from agent_foundry.responders.stdin import StdinResponder


def _make_context(request_id: str = "req-1") -> ResponderContext:
    return ResponderContext(
        run_id="run-1",
        request_id=request_id,
        agent_name="reviewer",
        invocation=1,
        turn=4,
    )


def _queue_input(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> None:
    """Patch ``builtins.input`` to return successive lines."""

    it: Iterator[str] = iter(lines)

    def fake_input(prompt: str = "") -> str:
        # StdinResponder is expected to write its prompt via stdout
        # directly (not via the ``input()`` prompt arg). If it uses
        # ``input(prompt)`` we still tolerate that by ignoring the arg.
        return next(it)

    monkeypatch.setattr("builtins.input", fake_input)


@pytest.mark.asyncio
class TestStdinResponderClarificationHappyPath:
    async def test_returns_piped_answer(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _queue_input(monkeypatch, ["use option A"])
        responder = StdinResponder()
        request = ClarificationRequest(
            question="Which variant?",
            options=["A", "B"],
            agent_name="reviewer",
            invocation=1,
            turn=4,
        )

        response = await responder.respond(request, _make_context())

        assert isinstance(response, ResponderResponse)
        assert response.answer == "use option A"

    async def test_prompt_discloses_identity_and_question(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _queue_input(monkeypatch, ["ok"])
        responder = StdinResponder()
        request = ClarificationRequest(
            question="Which variant?",
            options=["A", "B"],
            agent_name="reviewer",
            invocation=2,
            turn=4,
        )

        await responder.respond(request, _make_context())

        captured = capsys.readouterr().out
        assert "clarification" in captured.lower()
        assert "reviewer" in captured
        assert "2" in captured  # invocation disclosed
        assert "turn 4" in captured
        assert "Which variant?" in captured


@pytest.mark.asyncio
class TestStdinResponderPermissionHappyPath:
    async def test_prompt_distinguishes_permission_from_clarification(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _queue_input(monkeypatch, ["approve"])
        responder = StdinResponder()
        request = PermissionRequest(
            action_summary="delete /tmp/foo",
            risk_level="medium",
            why_needed="cleanup",
            agent_name="reviewer",
            invocation=1,
            turn=4,
        )

        response = await responder.respond(request, _make_context())

        assert response.answer == "approve"
        captured = capsys.readouterr().out
        assert "permission" in captured.lower()
        assert "clarification" not in captured.lower()
        assert "delete /tmp/foo" in captured
        assert "reviewer" in captured


@pytest.mark.asyncio
class TestStdinResponderConcurrency:
    async def test_concurrent_calls_serialized_with_queue_marker(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Two answers queued in arrival order. The first respond() must
        # read the first line; the second respond() blocks on the lock
        # and then reads the second line.
        answers = ["first-answer", "second-answer"]
        answer_iter = iter(answers)
        # Use an event to let us observe that the second coroutine
        # waited (via queue depth marker) before the first released.
        release = asyncio.Event()
        started_first = asyncio.Event()

        def fake_input(prompt: str = "") -> str:
            value = next(answer_iter)
            if value == "first-answer":
                started_first.set()
                # Block the first call until the second has queued.
                # This is synchronous, so we rely on the test driver
                # setting ``release`` before invoking this via executor.
                # The call is run in a thread by StdinResponder.
                release.wait()
            return value

        monkeypatch.setattr("builtins.input", fake_input)

        responder = StdinResponder()
        req1 = ClarificationRequest(question="Q1?", agent_name="reviewer", invocation=1, turn=1)
        req2 = ClarificationRequest(question="Q2?", agent_name="reviewer", invocation=1, turn=2)

        async def first() -> ResponderResponse:
            return await responder.respond(req1, _make_context("req-1"))

        async def second() -> ResponderResponse:
            # Ensure the first call has acquired the lock and started
            # its (blocking) input read before we enqueue the second.
            await started_first.wait()
            return await responder.respond(req2, _make_context("req-2"))

        task1 = asyncio.create_task(first())
        task2 = asyncio.create_task(second())

        # Give task2 a chance to reach the lock and emit its queued
        # prompt (with queue depth marker) before we release task1.
        await asyncio.sleep(0.05)
        release.set()

        r1, r2 = await asyncio.gather(task1, task2)

        assert r1.answer == "first-answer"
        assert r2.answer == "second-answer"

        captured = capsys.readouterr().out
        # First prompt has no queue marker; second prompt shows queue
        # depth of at least 1 (formatted like "queue 1").
        assert "queue 1" in captured.lower() or "queue: 1" in captured.lower()
        # Ordering: Q1's prompt appears before Q2's prompt.
        q1_idx = captured.find("Q1?")
        q2_idx = captured.find("Q2?")
        assert q1_idx != -1 and q2_idx != -1
        assert q1_idx < q2_idx


@pytest.mark.asyncio
class TestStdinResponderStdinFallback:
    """Also verify the responder works with an ``io.StringIO`` stdin
    stub, in case the implementation reads ``sys.stdin`` directly rather
    than calling ``input()``.
    """

    async def test_reads_from_sys_stdin_when_input_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("piped\n"))
        # Force any ``input()`` fallback to raise so we exercise the
        # sys.stdin path only if the implementation prefers it.
        monkeypatch.setattr(
            "builtins.input",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(EOFError()),
        )
        responder = StdinResponder()
        request = ClarificationRequest(
            question="pipe?",
            agent_name="reviewer",
            invocation=0,
            turn=0,
        )

        # Either path is acceptable; we assert only that *some* answer
        # comes back rather than hanging or raising.
        try:
            response = await responder.respond(request, _make_context())
        except EOFError:
            pytest.skip("implementation uses input(); covered by other tests")
        else:
            assert response.answer.strip() == "piped"
