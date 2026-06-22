"""Tests for ``agent_foundry.evals.runners.pydantic_evals.PydanticEvalsRunner``."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agent_foundry.ai_models.inference import (
    InferenceParameters,
    InferenceProvider,
    InferenceRequest,
    InferenceResult,
)
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.constructs.ai_call import AICall, ModelInput
from agent_foundry.constructs.models import AgentAction, ContainerReusePolicy
from agent_foundry.evals.agent_foundry_tasks import build_invoke_ai_call_task
from agent_foundry.evals.models import (
    AgentTarget,
    AICallTarget,
    Case,
    Dataset,
    EqualsExpectedSpec,
    EvalSuite,
    RunResult,
)
from agent_foundry.evals.runners.pydantic_evals import PydanticEvalsRunner


class _Input(BaseModel):
    text: str


class _Output(BaseModel):
    result: str


def _stub_executor(*, construct, prompt, instructions, run_ctx) -> _Output:
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
    dataset = Dataset(
        name="ds",
        cases=[
            Case(name="c1", inputs=_Input(text="a"), expected_output=_Output(result="A")),
            Case(name="c2", inputs=_Input(text="b"), expected_output=_Output(result="B")),
        ],
        evaluators=[EqualsExpectedSpec()],
    )
    return EvalSuite(
        name="test_suite",
        target=AgentTarget(agent=_make_agent()),
        dataset=dataset,
        invocations_per_case=invocations_per_case,
    )


@pytest.mark.asyncio
async def test_run_returns_run_result() -> None:
    """runner.run returns a RunResult with metadata populated."""
    suite = _make_suite(invocations_per_case=1)

    async def echo_task(input_state: _Input) -> _Output:
        return _Output(result=input_state.text.upper())

    result = await PydanticEvalsRunner().run(suite, task=echo_task)

    assert isinstance(result, RunResult)
    assert result.suite_name == "test_suite"
    assert result.invocations_per_case == 1
    assert result.started_at <= result.ended_at


@pytest.mark.asyncio
async def test_run_uses_repeat_for_invocations() -> None:
    """invocations_per_case=N produces N entries per case in the report."""
    suite = _make_suite(invocations_per_case=3)

    async def echo_task(input_state: _Input) -> _Output:
        return _Output(result=input_state.text.upper())

    result = await PydanticEvalsRunner().run(suite, task=echo_task)

    # 2 cases x 3 repeats = 6 entries in the single report.
    assert len(result.report.cases) == 6


@pytest.mark.asyncio
async def test_run_calls_task_for_each_case_invocation() -> None:
    """Each (case, invocation) pair triggers exactly one task call."""
    suite = _make_suite(invocations_per_case=2)
    received: list[str] = []

    async def recording_task(input_state: _Input) -> _Output:
        received.append(input_state.text)
        return _Output(result=input_state.text.upper())

    await PydanticEvalsRunner().run(suite, task=recording_task)

    # 2 cases x 2 invocations = 4 task calls.
    assert sorted(received) == ["a", "a", "b", "b"]


@pytest.mark.asyncio
async def test_run_task_failure_is_per_case_not_whole_run() -> None:
    """A task that raises for one case must not abort the whole evaluation."""
    suite = _make_suite(invocations_per_case=1)

    async def flaky_task(input_state: _Input) -> _Output:
        if input_state.text == "a":
            raise RuntimeError("agent crashed on a")
        return _Output(result=input_state.text.upper())

    result = await PydanticEvalsRunner().run(suite, task=flaky_task)

    # The single invocation should still produce a report, with case "c1"
    # captured as a failure and "c2" as a success.
    report = result.report
    case_names = {c.name for c in report.cases} | {f.name for f in report.failures}
    assert case_names == {"c1", "c2"}


@pytest.mark.asyncio
async def test_run_generates_unique_run_ids() -> None:
    """Each runner.run call produces a distinct run_id."""
    suite = _make_suite(invocations_per_case=1)

    async def task(input_state: _Input) -> _Output:
        return _Output(result=input_state.text.upper())

    runner = PydanticEvalsRunner()
    r1 = await runner.run(suite, task=task)
    r2 = await runner.run(suite, task=task)
    assert r1.run_id != r2.run_id


# --- build_invoke_ai_call_task ---


def _make_ai_call(captured: list[InferenceRequest]) -> AICall[_Input, _Output]:
    class _CapturingProvider(InferenceProvider):
        async def __call__(self, request: InferenceRequest) -> InferenceResult:
            captured.append(request)
            return InferenceResult(output=_Output(result=request.prompt.upper()))

        async def close(self) -> None:
            pass

    entry = ModelEntry(
        model_id="fake",
        provider=_CapturingProvider(),
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )
    return AICall[_Input, _Output](
        model_input=ModelInput[_Input](
            instructions="i",
            prompt=lambda s: s.text,
        ),
        parameters=InferenceParameters(max_tokens=128),
        model=entry,
    )


def _make_ai_call_suite(
    captured: list[InferenceRequest], invocations_per_case: int = 1
) -> EvalSuite:
    dataset = Dataset(
        name="ds",
        cases=[
            Case(name="c1", inputs=_Input(text="a"), expected_output=_Output(result="A")),
            Case(name="c2", inputs=_Input(text="b"), expected_output=_Output(result="B")),
        ],
        evaluators=[EqualsExpectedSpec()],
    )
    return EvalSuite(
        name="ai_call_suite",
        target=AICallTarget(ai_call=_make_ai_call(captured)),
        dataset=dataset,
        invocations_per_case=invocations_per_case,
    )


@pytest.mark.asyncio
async def test_build_invoke_ai_call_task_passes_input_through_to_provider() -> None:
    captured: list[InferenceRequest] = []
    call = _make_ai_call(captured)
    task = build_invoke_ai_call_task(call)

    output = await task(_Input(text="hello"))

    assert len(captured) == 1
    assert captured[0].prompt == "hello"
    assert isinstance(output, _Output)
    assert output.result == "HELLO"


@pytest.mark.asyncio
async def test_run_with_ai_call_target_end_to_end() -> None:
    captured: list[InferenceRequest] = []
    suite = _make_ai_call_suite(captured, invocations_per_case=1)
    task = build_invoke_ai_call_task(_get_ai_call(suite))

    result = await PydanticEvalsRunner().run(suite, task=task)

    # 2 cases x 1 invocation = 2 provider calls
    assert len(captured) == 2
    # Report has the two case entries — successes via EqualsExpected.
    assert {c.name for c in result.report.cases} == {"c1", "c2"}


def _get_ai_call(suite: EvalSuite) -> AICall:
    assert isinstance(suite.target, AICallTarget)
    return suite.target.ai_call
