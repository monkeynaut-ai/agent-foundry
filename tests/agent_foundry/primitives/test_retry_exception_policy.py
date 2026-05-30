"""Tests for Retry body-exception policy.

Covers:
  - PROPAGATE default: existing behaviour unchanged (A1)
  - CATCH_AND_CONTINUE: exception consumed, state rolled back, retry continues (A2, A4)
  - Interim exhaustion is fail-closed: the automated loop raises RetryAborted
  - Lifecycle events emitted per failed attempt (A5)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.compiler.primitive_compiler import compile_runtime_plan, get_type_args
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.lifecycle_writer import LifecycleWriter
from agent_foundry.primitives.models import FunctionAction, Retry, RetryExceptionPolicy
from agent_foundry.primitives.plan import PrimitivePlan
from agent_foundry.primitives.retry_types import RetryAborted

# ---------------------------------------------------------------------------
# State model
# ---------------------------------------------------------------------------


class _S(BaseModel):
    value: int = 0
    done: bool = False


# ---------------------------------------------------------------------------
# Capturing lifecycle writer
# ---------------------------------------------------------------------------


@dataclass
class _CapturingWriter(LifecycleWriter):
    events: list[dict] = field(default_factory=list)

    def append(self, event_type: LifecycleEvent, **fields: Any) -> None:
        self.events.append({"type": event_type, **fields})

    def append_run_event(self, kind: str, **fields: Any) -> None:
        pass

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_context(writer: LifecycleWriter | None = None, tmp_path: Any = None):
    """Context manager that installs a RunContext with the given writer."""
    import pathlib
    import tempfile

    from agent_foundry.orchestration.run_context import (
        NoOpLifecycleWriter,
        RunContext,
        current_run_context,
    )

    path = tmp_path if tmp_path is not None else pathlib.Path(tempfile.mkdtemp())
    ctx = RunContext(
        run_id="retry-policy-test",
        artifacts_dir=path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=writer or NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    return current_run_context, ctx


def _install_run_context(writer: LifecycleWriter | None = None):
    ctx_var, ctx = _run_context(writer)
    return ctx_var.set(ctx), ctx_var


async def _compile_and_run(
    retry: Retry,
    initial: _S,
    writer: LifecycleWriter | None = None,
) -> Any:
    token, ctx_var = _install_run_context(writer)
    try:
        _, root_out = get_type_args(retry)
        plan = PrimitivePlan(root=retry)
        graph = compile_runtime_plan(plan)
        result = await graph.ainvoke(initial.model_dump())
        return root_out.model_validate(result)
    finally:
        ctx_var.reset(token)


def _raising_body(exc: Exception) -> FunctionAction:
    def _raise(s: _S) -> _S:
        raise exc

    return FunctionAction[_S, _S](function=_raise)


def _counter_body(succeed_on_attempt: int) -> FunctionAction:
    """Body that raises RuntimeError on attempts < succeed_on_attempt, then returns done=True."""
    call_count = {"n": 0}

    def _fn(s: _S) -> _S:
        call_count["n"] += 1
        if call_count["n"] < succeed_on_attempt:
            raise RuntimeError(f"failing attempt {call_count['n']}")
        return _S(value=s.value + 1, done=True)

    return FunctionAction[_S, _S](function=_fn)


def _always_succeed_body() -> FunctionAction:
    """Returns done=False always — used for CONDITION_NOT_MET exhaustion."""
    call_count = {"n": 0}

    def _fn(s: _S) -> _S:
        call_count["n"] += 1
        return _S(value=call_count["n"], done=False)

    return FunctionAction[_S, _S](function=_fn)


# ---------------------------------------------------------------------------
# A1 — PROPAGATE default: exception propagates unchanged
# ---------------------------------------------------------------------------


class TestPropagate:
    @pytest.mark.asyncio
    async def test_propagate_is_default(self) -> None:
        """A1: default exception_policy is PROPAGATE; body raise propagates."""
        retry = Retry[_S, _S](
            max_attempts=3,
            until=lambda s: s.done,
            body=_raising_body(ValueError("boom")),
        )
        assert retry.exception_policy == RetryExceptionPolicy.PROPAGATE

        with pytest.raises(ValueError, match="boom"):
            await _compile_and_run(retry, _S())

    @pytest.mark.asyncio
    async def test_explicit_propagate_raises(self) -> None:
        """A1: explicit PROPAGATE also re-raises without consuming attempts."""
        retry = Retry[_S, _S](
            max_attempts=3,
            until=lambda s: s.done,
            body=_raising_body(RuntimeError("explicit-propagate")),
            exception_policy=RetryExceptionPolicy.PROPAGATE,
        )

        with pytest.raises(RuntimeError, match="explicit-propagate"):
            await _compile_and_run(retry, _S())


# ---------------------------------------------------------------------------
# A2 — CATCH_AND_CONTINUE: exception consumed, next attempt succeeds
# ---------------------------------------------------------------------------


class TestTreatAsFailure:
    @pytest.mark.asyncio
    async def test_first_attempt_raises_second_succeeds(self) -> None:
        """A2: body raises on attempt 1, succeeds on attempt 2 → Retry exits with attempt-2 output."""
        retry = Retry[_S, _S](
            max_attempts=3,
            until=lambda s: s.done,
            body=_counter_body(succeed_on_attempt=2),
            exception_policy=RetryExceptionPolicy.CATCH_AND_CONTINUE,
        )
        result = await _compile_and_run(retry, _S(value=0))
        assert result.done is True
        assert result.value == 1  # body incremented once on the successful attempt

    @pytest.mark.asyncio
    async def test_all_attempts_raise_exhaustion_is_fail_closed(self) -> None:
        """CATCH_AND_CONTINUE + all attempts raise + no until() pass → RetryAborted (fail-closed)."""
        retry = Retry[_S, _S](
            max_attempts=2,
            until=lambda s: s.done,
            body=_raising_body(RuntimeError("always")),
            exception_policy=RetryExceptionPolicy.CATCH_AND_CONTINUE,
        )
        with pytest.raises(RetryAborted):
            await _compile_and_run(retry, _S(value=42, done=False))


# ---------------------------------------------------------------------------
# Exhaustion without until() satisfied — interim fail-closed
# ---------------------------------------------------------------------------


class TestExhaustionFailClosed:
    @pytest.mark.asyncio
    async def test_condition_never_met_exhaustion_raises(self) -> None:
        """Condition never met across all attempts → RetryAborted (fail-closed)."""
        retry = Retry[_S, _S](
            max_attempts=2,
            until=lambda s: s.done,
            body=_always_succeed_body(),
        )
        with pytest.raises(RetryAborted):
            await _compile_and_run(retry, _S(value=0))


# ---------------------------------------------------------------------------
# A4 — state rollback: partial mutations are discarded
# ---------------------------------------------------------------------------


class TestStateRollback:
    @pytest.mark.asyncio
    async def test_partial_mutation_rolled_back(self) -> None:
        """A4: body that would mutate state then raise → next attempt sees pre-mutation state."""
        seen_values: list[int] = []

        call_count = {"n": 0}

        def body_fn(s: _S) -> _S:
            call_count["n"] += 1
            seen_values.append(s.value)
            if call_count["n"] < 3:
                raise RuntimeError("transient")
            return _S(value=s.value + 1, done=True)

        retry = Retry[_S, _S](
            max_attempts=3,
            until=lambda s: s.done,
            body=FunctionAction[_S, _S](function=body_fn),
            exception_policy=RetryExceptionPolicy.CATCH_AND_CONTINUE,
        )
        result = await _compile_and_run(retry, _S(value=5))

        # All attempts started from value=5 (the snapshot is restored each time)
        assert all(v == 5 for v in seen_values), f"Expected all 5, got {seen_values}"
        assert result.done is True
        assert result.value == 6


# ---------------------------------------------------------------------------
# A5 — RETRY_ATTEMPT_FAILED lifecycle events emitted per failure
# ---------------------------------------------------------------------------


class TestLifecycleEvents:
    @pytest.mark.asyncio
    async def test_attempt_failed_event_emitted_per_exception(self) -> None:
        """A5: RETRY_ATTEMPT_FAILED emitted with attempt_num, exception_type, exception_message."""
        writer = _CapturingWriter()

        retry = Retry[_S, _S](
            max_attempts=3,
            until=lambda s: s.done,
            body=_counter_body(succeed_on_attempt=3),
            exception_policy=RetryExceptionPolicy.CATCH_AND_CONTINUE,
        )
        await _compile_and_run(retry, _S(), writer=writer)

        failed_events = [
            e for e in writer.events if e["type"] == LifecycleEvent.RETRY_ATTEMPT_FAILED
        ]
        assert len(failed_events) == 2  # attempts 1 and 2 failed; attempt 3 succeeded

        assert failed_events[0]["attempt_num"] == 1
        assert failed_events[0]["exception_type"] == "RuntimeError"
        assert "failing attempt 1" in failed_events[0]["exception_message"]

        assert failed_events[1]["attempt_num"] == 2
        assert failed_events[1]["exception_type"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_no_events_emitted_under_propagate(self) -> None:
        """Under PROPAGATE policy no RETRY_ATTEMPT_FAILED events are emitted."""
        writer = _CapturingWriter()

        retry = Retry[_S, _S](
            max_attempts=3,
            until=lambda s: s.done,
            body=_raising_body(RuntimeError("boom")),
        )
        with pytest.raises(RuntimeError):
            await _compile_and_run(retry, _S(), writer=writer)

        failed_events = [
            e for e in writer.events if e["type"] == LifecycleEvent.RETRY_ATTEMPT_FAILED
        ]
        assert failed_events == []
