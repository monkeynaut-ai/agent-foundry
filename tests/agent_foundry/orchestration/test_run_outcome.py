"""Tests for the ``RunOutcome`` terminal-outcome envelope.

``RunOutcome`` is the single typed value every ``run_primitive_plan``
invocation ends with: a discriminated union of completed / aborted /
failed, routed by a ``kind`` discriminator.
"""

from __future__ import annotations

from pydantic import BaseModel, TypeAdapter

from agent_foundry.orchestration.run_outcome import (
    FailureKind,
    RunAborted,
    RunCompleted,
    RunFailed,
    RunOutcome,
    RunOutcomeKind,
)


class _SomeModel(BaseModel):
    x: int


def test_run_completed_round_trips() -> None:
    out = RunCompleted(output=_SomeModel(x=1))
    assert out.kind is RunOutcomeKind.COMPLETED
    assert isinstance(out.output, _SomeModel)
    assert out.output.x == 1


def test_run_aborted_carries_reason() -> None:
    out = RunAborted(reason="cannot-converge")
    assert out.kind is RunOutcomeKind.ABORTED
    assert out.reason == "cannot-converge"


def test_run_aborted_reason_defaults_empty() -> None:
    out = RunAborted()
    assert out.kind is RunOutcomeKind.ABORTED
    assert out.reason == ""


def test_run_failed_carries_error_kind() -> None:
    out = RunFailed(
        error_kind=FailureKind.BACKSTOP,
        error_type="ResolverDidNotConvergeError",
        message="did not converge",
    )
    assert out.kind is RunOutcomeKind.FAILED
    assert out.error_kind is FailureKind.BACKSTOP
    assert out.error_type == "ResolverDidNotConvergeError"
    assert out.message == "did not converge"


def test_failure_kind_members() -> None:
    assert FailureKind.BACKSTOP.value == "backstop"
    assert FailureKind.CRASH.value == "crash"


def test_run_outcome_kind_members() -> None:
    assert RunOutcomeKind.COMPLETED.value == "completed"
    assert RunOutcomeKind.ABORTED.value == "aborted"
    assert RunOutcomeKind.FAILED.value == "failed"


def test_discriminated_union_dispatches_on_kind_aborted() -> None:
    adapter = TypeAdapter(RunOutcome)
    got = adapter.validate_python({"kind": "aborted", "reason": "r"})
    assert isinstance(got, RunAborted)
    assert got.reason == "r"


def test_discriminated_union_dispatches_on_kind_failed() -> None:
    adapter = TypeAdapter(RunOutcome)
    got = adapter.validate_python(
        {
            "kind": "failed",
            "error_kind": "crash",
            "error_type": "RuntimeError",
            "message": "boom",
        }
    )
    assert isinstance(got, RunFailed)
    assert got.error_kind is FailureKind.CRASH
