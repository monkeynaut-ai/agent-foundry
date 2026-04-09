"""Tests for AgentTurnEnvelope envelope and its four variants."""

import pytest
from pydantic import BaseModel, ValidationError

from agent_foundry.acp.agent_turn_envelope import (
    AgentTurnEnvelope,
    ClarificationOutcome,
    FailureOutcome,
    PermissionOutcome,
    SuccessOutcome,
    TurnOutcomeKind,
)


class _TrivialPayload(BaseModel):
    message: str


_TrivialEnvelope = AgentTurnEnvelope[_TrivialPayload]


class TestSuccessOutcome:
    def test_given_payload_when_constructed_then_kind_is_success(self):
        outcome = SuccessOutcome[_TrivialPayload](payload=_TrivialPayload(message="ok"))
        assert outcome.kind is TurnOutcomeKind.SUCCESS

    def test_given_envelope_wrapping_success_when_validated_then_payload_typed(self):
        data = {"outcome": {"kind": "success", "payload": {"message": "ok"}}}
        env = _TrivialEnvelope.model_validate(data)
        assert isinstance(env.outcome, SuccessOutcome)
        assert env.outcome.payload.message == "ok"


class TestClarificationOutcome:
    def test_given_envelope_wrapping_clarification_when_validated_then_typed(self):
        data = {
            "outcome": {
                "kind": "clarification_needed",
                "question": "which file?",
                "options": ["a.py", "b.py"],
            }
        }
        env = _TrivialEnvelope.model_validate(data)
        assert isinstance(env.outcome, ClarificationOutcome)
        assert env.outcome.question == "which file?"
        assert env.outcome.blocking is True

    def test_given_clarification_missing_question_when_validated_then_raises(self):
        data = {"outcome": {"kind": "clarification_needed"}}
        with pytest.raises(ValidationError):
            _TrivialEnvelope.model_validate(data)


class TestPermissionOutcome:
    def test_given_envelope_wrapping_permission_when_validated_then_typed(self):
        data = {
            "outcome": {
                "kind": "permission_needed",
                "action": "delete /workspace/old",
                "risk_level": "high",
                "why_needed": "cleanup",
            }
        }
        env = _TrivialEnvelope.model_validate(data)
        assert isinstance(env.outcome, PermissionOutcome)
        assert env.outcome.action == "delete /workspace/old"
        assert env.outcome.risk_level == "high"
        assert env.outcome.why_needed == "cleanup"


class TestFailureOutcome:
    def test_given_envelope_wrapping_failure_when_validated_then_typed(self):
        data = {
            "outcome": {
                "kind": "failed",
                "reason": "premise wrong: target file does not exist",
                "attempted_approaches": ["grep", "glob"],
            }
        }
        env = _TrivialEnvelope.model_validate(data)
        assert isinstance(env.outcome, FailureOutcome)
        assert env.outcome.reason.startswith("premise wrong")
        assert env.outcome.attempted_approaches == ["grep", "glob"]

    def test_given_failure_missing_reason_when_validated_then_raises(self):
        data = {"outcome": {"kind": "failed"}}
        with pytest.raises(ValidationError):
            _TrivialEnvelope.model_validate(data)


class TestDiscriminatorDispatch:
    def test_given_unknown_kind_when_validated_then_raises(self):
        data = {"outcome": {"kind": "nonsense"}}
        with pytest.raises(ValidationError):
            _TrivialEnvelope.model_validate(data)

    def test_given_missing_kind_when_validated_then_raises(self):
        data = {"outcome": {}}
        with pytest.raises(ValidationError):
            _TrivialEnvelope.model_validate(data)


class TestRoundTrip:
    def test_given_each_outcome_when_round_tripped_then_equals(self):
        envelopes = [
            _TrivialEnvelope(
                outcome=SuccessOutcome[_TrivialPayload](payload=_TrivialPayload(message="x"))
            ),
            _TrivialEnvelope(outcome=ClarificationOutcome(question="q")),
            _TrivialEnvelope(
                outcome=PermissionOutcome(action="a", risk_level="low", why_needed="w")
            ),
            _TrivialEnvelope(outcome=FailureOutcome(reason="r")),
        ]
        for env in envelopes:
            assert _TrivialEnvelope.model_validate_json(env.model_dump_json()) == env
