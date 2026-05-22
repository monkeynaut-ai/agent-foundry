"""Tests for ``agent_foundry.evals.models``."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EqualsExpected
from pydantic_evals.reporting import EvaluationReport

from agent_foundry.ai_models.inference import InferenceParameters
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.evals.models import (
    AgentTarget,
    AICallTarget,
    EvalSuite,
    EvalTargetKind,
    RunResult,
)
from agent_foundry.primitives.ai_call import AICall, ModelInput
from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy


class _Input(BaseModel):
    text: str


class _Output(BaseModel):
    result: str


def _stub_executor(*, primitive, prompt, instructions, run_ctx) -> _Output:
    return _Output(result="")


def _make_dataset() -> Dataset[_Input, _Output, None]:
    return Dataset[_Input, _Output, None](
        name="ds",
        cases=[
            Case(name="c1", inputs=_Input(text="a"), expected_output=_Output(result="A")),
        ],
        evaluators=[EqualsExpected()],
    )


def _make_agent() -> AgentAction[_Input, _Output]:
    return AgentAction[_Input, _Output](
        name="test_agent",
        prompt_builder=lambda inp: inp.text,
        instructions_provider=lambda inp: "do the thing",
        executor=_stub_executor,
        reuse_policy=ContainerReusePolicy.REUSE_RESUME,
        model="claude-sonnet-4-6",
    )


def _make_ai_call() -> AICall[_Input, _Output]:
    entry = ModelEntry(
        model_id="fake",
        provider=object(),  # type: ignore[arg-type]  # not invoked in model-only tests
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )
    return AICall[_Input, _Output](
        model_input=ModelInput[_Input](instructions="i", prompt="p"),
        parameters=InferenceParameters(max_tokens=128),
        model=entry,
    )


# --- EvalSuite — agent target ---


def test_eval_suite_with_agent_target() -> None:
    agent = _make_agent()
    dataset = _make_dataset()
    suite = EvalSuite(
        name="test_suite",
        target=AgentTarget(agent=agent),
        dataset=dataset,
        invocations_per_case=3,
    )
    assert suite.name == "test_suite"
    assert suite.target.kind is EvalTargetKind.AGENT
    assert isinstance(suite.target, AgentTarget)
    assert suite.target.agent is agent
    assert suite.dataset is dataset
    assert suite.invocations_per_case == 3


# --- EvalSuite — AICall target ---


def test_eval_suite_with_ai_call_target() -> None:
    call = _make_ai_call()
    dataset = _make_dataset()
    suite = EvalSuite(
        name="ai_call_suite",
        target=AICallTarget(ai_call=call),
        dataset=dataset,
        invocations_per_case=1,
    )
    assert suite.target.kind is EvalTargetKind.AI_CALL
    assert isinstance(suite.target, AICallTarget)
    assert suite.target.ai_call is call


# --- EvalSuite — discriminator behavior ---


def test_eval_target_discriminator_picks_agent_variant() -> None:
    from pydantic import TypeAdapter

    from agent_foundry.evals.models import EvalTarget

    adapter = TypeAdapter(EvalTarget)
    parsed = adapter.validate_python({"kind": "agent", "agent": _make_agent()})
    assert isinstance(parsed, AgentTarget)


def test_eval_target_discriminator_picks_ai_call_variant() -> None:
    from pydantic import TypeAdapter

    from agent_foundry.evals.models import EvalTarget

    adapter = TypeAdapter(EvalTarget)
    parsed = adapter.validate_python({"kind": "ai_call", "ai_call": _make_ai_call()})
    assert isinstance(parsed, AICallTarget)


def test_eval_target_rejects_unknown_kind() -> None:
    from pydantic import TypeAdapter

    from agent_foundry.evals.models import EvalTarget

    adapter = TypeAdapter(EvalTarget)
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "bogus"})


# --- EvalSuite — validation ---


def test_eval_suite_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        EvalSuite(
            name="",
            target=AgentTarget(agent=_make_agent()),
            dataset=_make_dataset(),
            invocations_per_case=1,
        )


def test_eval_suite_rejects_zero_invocations() -> None:
    with pytest.raises(ValidationError):
        EvalSuite(
            name="s",
            target=AgentTarget(agent=_make_agent()),
            dataset=_make_dataset(),
            invocations_per_case=0,
        )


def test_eval_suite_rejects_negative_invocations() -> None:
    with pytest.raises(ValidationError):
        EvalSuite(
            name="s",
            target=AgentTarget(agent=_make_agent()),
            dataset=_make_dataset(),
            invocations_per_case=-1,
        )


# --- RunResult ---


def test_run_result_construction() -> None:
    started = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)
    ended = datetime(2026, 5, 15, 12, 0, 5, tzinfo=UTC)
    report = EvaluationReport[_Input, _Output, None](name="r1", cases=[])
    result = RunResult(
        run_id="run_001",
        suite_name="test_suite",
        started_at=started,
        ended_at=ended,
        invocations_per_case=1,
        report=report,
    )
    assert result.run_id == "run_001"
    assert result.suite_name == "test_suite"
    assert result.started_at == started
    assert result.ended_at == ended
    assert result.invocations_per_case == 1
    assert result.report is report


def test_run_result_rejects_empty_run_id() -> None:
    report = EvaluationReport[_Input, _Output, None](name="r1", cases=[])
    with pytest.raises(ValidationError):
        RunResult(
            run_id="",
            suite_name="s",
            started_at=datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC),
            ended_at=datetime(2026, 5, 15, 12, 0, 5, tzinfo=UTC),
            invocations_per_case=1,
            report=report,
        )
