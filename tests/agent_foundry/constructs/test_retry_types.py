"""Tests for retry_types module — RetryExhaustionReason, AttemptFailure, RetryExhaustion."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

import pytest
from pydantic import BaseModel, ValidationError

from agent_foundry.constructs.retry_types import (
    AttemptFailure,
    AttemptOutcome,
    DispositionKind,
    ResolverDidNotConvergeError,
    ResolverDisposition,
    RetryAborted,
    RetryExhaustion,
    RetryExhaustionReason,
)


class _StateA(BaseModel):
    value: int = 0
    done: bool = False


class _StateB(BaseModel):
    name: str


class TestRetryExhaustionReason:
    def test_is_strenum(self) -> None:
        assert issubclass(RetryExhaustionReason, StrEnum)

    def test_has_exactly_three_members(self) -> None:
        assert set(RetryExhaustionReason) == {
            RetryExhaustionReason.CONDITION_NOT_MET,
            RetryExhaustionReason.BODY_EXCEPTIONS,
            RetryExhaustionReason.MIXED,
        }

    def test_wire_values(self) -> None:
        assert RetryExhaustionReason.CONDITION_NOT_MET == "condition_not_met"
        assert RetryExhaustionReason.BODY_EXCEPTIONS == "body_exceptions"
        assert RetryExhaustionReason.MIXED == "mixed"


class TestAttemptFailure:
    def test_constructs_with_required_fields(self) -> None:
        ts = datetime.now(UTC)
        f = AttemptFailure(
            attempt_num=1,
            exception_type="ValueError",
            exception_message="bad value",
            timestamp=ts,
        )
        assert f.attempt_num == 1
        assert f.exception_type == "ValueError"
        assert f.exception_message == "bad value"
        assert f.timestamp == ts


class TestRetryExhaustion:
    def _ts(self) -> datetime:
        return datetime.now(UTC)

    def test_condition_not_met(self) -> None:
        state = _StateA(value=42)
        ex = RetryExhaustion(
            max_attempts=3,
            reason=RetryExhaustionReason.CONDITION_NOT_MET,
            last_state=state,
        )
        assert ex.max_attempts == 3
        assert ex.reason == RetryExhaustionReason.CONDITION_NOT_MET
        assert ex.attempt_failures == []
        assert ex.last_state.value == 42

    def test_body_exceptions_with_failures(self) -> None:
        state = _StateA()
        failure = AttemptFailure(
            attempt_num=1,
            exception_type="RuntimeError",
            exception_message="boom",
            timestamp=self._ts(),
        )
        ex = RetryExhaustion(
            max_attempts=1,
            reason=RetryExhaustionReason.BODY_EXCEPTIONS,
            attempt_failures=[failure],
            last_state=state,
        )
        assert ex.reason == RetryExhaustionReason.BODY_EXCEPTIONS
        assert len(ex.attempt_failures) == 1
        assert ex.attempt_failures[0].exception_type == "RuntimeError"

    def test_mixed(self) -> None:
        state = _StateA(value=1)
        failure = AttemptFailure(
            attempt_num=2,
            exception_type="IOError",
            exception_message="io fail",
            timestamp=self._ts(),
        )
        ex = RetryExhaustion(
            max_attempts=3,
            reason=RetryExhaustionReason.MIXED,
            attempt_failures=[failure],
            last_state=state,
        )
        assert ex.reason == RetryExhaustionReason.MIXED
        assert len(ex.attempt_failures) == 1

    def test_last_state_accepts_any_basemodel_subclass(self) -> None:
        state = _StateB(name="hello")
        ex = RetryExhaustion(
            max_attempts=1,
            reason=RetryExhaustionReason.CONDITION_NOT_MET,
            last_state=state,
        )
        assert ex.last_state.name == "hello"

    def test_attempt_failures_defaults_to_empty(self) -> None:
        ex = RetryExhaustion(
            max_attempts=2,
            reason=RetryExhaustionReason.CONDITION_NOT_MET,
            last_state=_StateA(),
        )
        assert ex.attempt_failures == []


def test_attempt_outcome_is_binary_str_enum() -> None:
    assert issubclass(AttemptOutcome, StrEnum)
    assert {m.value for m in AttemptOutcome} == {"passed", "not_passed"}


def test_existing_exhaustion_reason_reused_not_redefined() -> None:
    assert {m.value for m in RetryExhaustionReason} == {
        "condition_not_met",
        "body_exceptions",
        "mixed",
    }


def test_disposition_kind_members() -> None:
    assert {m.value for m in DispositionKind} == {"accept", "abort", "retry"}


def test_disposition_is_pure_routing_signal_no_state() -> None:
    assert "state" not in ResolverDisposition.model_fields
    assert set(ResolverDisposition.model_fields) == {"kind", "reason"}


def test_disposition_kind_required_reason_optional() -> None:
    d = ResolverDisposition(kind=DispositionKind.RETRY)
    assert d.kind == DispositionKind.RETRY
    assert d.reason == ""
    with pytest.raises(ValidationError):
        ResolverDisposition()


def test_abort_disposition_carries_reason() -> None:
    d = ResolverDisposition(kind=DispositionKind.ABORT, reason="operator gave up")
    assert d.kind == DispositionKind.ABORT
    assert d.reason == "operator gave up"


def test_disposition_round_trips_through_json() -> None:
    d = ResolverDisposition.model_validate({"kind": "accept"})
    assert d.kind == DispositionKind.ACCEPT


def test_retry_aborted_is_distinct_from_backstop() -> None:
    assert not issubclass(RetryAborted, ResolverDidNotConvergeError)
    assert not issubclass(ResolverDidNotConvergeError, RetryAborted)
    assert RetryAborted("r").reason == "r"
    exc = ResolverDidNotConvergeError(50)
    assert exc.ceiling == 50
    assert "50" in str(exc)
