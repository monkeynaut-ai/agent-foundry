"""Tests for ``agent_foundry.evals.models``."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EqualsExpected
from pydantic_evals.reporting import EvaluationReport

from agent_foundry.evals.models import EvalSuite, RunResult
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


# --- EvalSuite ---


def test_eval_suite_construction() -> None:
    """Suite holds the agent, dataset, and configuration."""
    agent = _make_agent()
    dataset = _make_dataset()
    suite = EvalSuite(
        name="test_suite",
        agent=agent,
        dataset=dataset,
        invocations_per_case=3,
    )
    assert suite.name == "test_suite"
    assert suite.agent is agent
    assert suite.dataset is dataset
    assert suite.invocations_per_case == 3


def test_eval_suite_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        EvalSuite(
            name="",
            agent=_make_agent(),
            dataset=_make_dataset(),
            invocations_per_case=1,
        )


def test_eval_suite_rejects_zero_invocations() -> None:
    with pytest.raises(ValidationError):
        EvalSuite(
            name="s",
            agent=_make_agent(),
            dataset=_make_dataset(),
            invocations_per_case=0,
        )


def test_eval_suite_rejects_negative_invocations() -> None:
    with pytest.raises(ValidationError):
        EvalSuite(
            name="s",
            agent=_make_agent(),
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
