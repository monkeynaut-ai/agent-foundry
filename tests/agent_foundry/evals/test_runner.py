"""Tests for ``agent_foundry.evals.runner``."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EqualsExpected

from agent_foundry.evals.models import EvalSuite, RunResult
from agent_foundry.evals.runner import run_suite
from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy


class _Input(BaseModel):
    text: str


class _Output(BaseModel):
    result: str


def _stub_executor(*, primitive, prompt, instructions, run_ctx) -> _Output:
    return _Output(result="")


def _make_agent() -> AgentAction[_Input, _Output]:
    return AgentAction[_Input, _Output](
        name="test_agent",
        prompt_builder=lambda inp: inp.text,
        instructions_provider=lambda inp: "do the thing",
        executor=_stub_executor,
        reuse_policy=ContainerReusePolicy.REUSE_RESUME,
        model="claude-sonnet-4-6",
    )


def _make_suite(invocations_per_case: int = 1) -> EvalSuite:
    dataset = Dataset[_Input, _Output, None](
        name="ds",
        cases=[
            Case(name="c1", inputs=_Input(text="a"), expected_output=_Output(result="A")),
            Case(name="c2", inputs=_Input(text="b"), expected_output=_Output(result="B")),
        ],
        evaluators=[EqualsExpected()],
    )
    return EvalSuite(
        name="test_suite",
        agent=_make_agent(),
        dataset=dataset,
        invocations_per_case=invocations_per_case,
    )


@pytest.mark.asyncio
async def test_run_suite_returns_run_result() -> None:
    """run_suite returns a RunResult with metadata populated."""
    suite = _make_suite(invocations_per_case=1)

    async def echo_task(input_state: _Input) -> _Output:
        return _Output(result=input_state.text.upper())

    result = await run_suite(suite, task=echo_task)

    assert isinstance(result, RunResult)
    assert result.suite_name == "test_suite"
    assert result.invocations_per_case == 1
    assert result.started_at <= result.ended_at


@pytest.mark.asyncio
async def test_run_suite_uses_repeat_for_invocations() -> None:
    """invocations_per_case=N produces N entries per case in the report."""
    suite = _make_suite(invocations_per_case=3)

    async def echo_task(input_state: _Input) -> _Output:
        return _Output(result=input_state.text.upper())

    result = await run_suite(suite, task=echo_task)

    # 2 cases x 3 repeats = 6 entries in the single report.
    assert len(result.report.cases) == 6


@pytest.mark.asyncio
async def test_run_suite_calls_task_for_each_case_invocation() -> None:
    """Each (case, invocation) pair triggers exactly one task call."""
    suite = _make_suite(invocations_per_case=2)
    received: list[str] = []

    async def recording_task(input_state: _Input) -> _Output:
        received.append(input_state.text)
        return _Output(result=input_state.text.upper())

    await run_suite(suite, task=recording_task)

    # 2 cases x 2 invocations = 4 task calls.
    assert sorted(received) == ["a", "a", "b", "b"]


@pytest.mark.asyncio
async def test_run_suite_task_failure_is_per_case_not_whole_run() -> None:
    """A task that raises for one case must not abort the whole evaluation."""
    suite = _make_suite(invocations_per_case=1)

    async def flaky_task(input_state: _Input) -> _Output:
        if input_state.text == "a":
            raise RuntimeError("agent crashed on a")
        return _Output(result=input_state.text.upper())

    result = await run_suite(suite, task=flaky_task)

    # The single invocation should still produce a report, with case "c1"
    # captured as a failure and "c2" as a success.
    report = result.report
    case_names = {c.name for c in report.cases} | {f.name for f in report.failures}
    assert case_names == {"c1", "c2"}


@pytest.mark.asyncio
async def test_run_suite_generates_unique_run_ids() -> None:
    """Each run_suite call produces a distinct run_id."""
    suite = _make_suite(invocations_per_case=1)

    async def task(input_state: _Input) -> _Output:
        return _Output(result=input_state.text.upper())

    r1 = await run_suite(suite, task=task)
    r2 = await run_suite(suite, task=task)
    assert r1.run_id != r2.run_id


@pytest.mark.asyncio
async def test_run_suite_passes_max_concurrency_through() -> None:
    """max_concurrency is forwarded to dataset.evaluate."""
    suite = _make_suite(invocations_per_case=1)
    calls: list[int] = []
    original_evaluate = suite.dataset.evaluate

    async def spy_evaluate(
        task: Callable[[_Input], Awaitable[_Output]],
        *,
        max_concurrency: int = 0,
        **kwargs: object,
    ):
        calls.append(max_concurrency)
        return await original_evaluate(task, max_concurrency=max_concurrency, **kwargs)  # type: ignore[arg-type]

    # Pydantic BaseModel blocks normal attribute assignment for non-field
    # names; bypass with object.__setattr__ for the duration of the test.
    object.__setattr__(suite.dataset, "evaluate", spy_evaluate)

    async def task(input_state: _Input) -> _Output:
        return _Output(result=input_state.text.upper())

    await run_suite(suite, task=task, max_concurrency=7)
    assert calls == [7]
