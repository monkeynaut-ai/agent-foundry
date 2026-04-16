"""Tests for responder request/response models."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from agent_foundry.acp.agent_turn_envelope import (
    ClarificationOutcome,
    PermissionOutcome,
)
from agent_foundry.responders.models import (
    ClarificationRequest,
    PermissionRequest,
    ResponderContext,
    ResponderKind,
    ResponderRequest,
    ResponderResponse,
    build_request_from_outcome,
)


class TestResponderKind:
    def test_has_exactly_two_members_with_expected_values(self):
        assert {m.value for m in ResponderKind} == {"clarification", "permission"}
        assert ResponderKind.CLARIFICATION.value == "clarification"
        assert ResponderKind.PERMISSION.value == "permission"


class TestClarificationRequest:
    def test_given_required_fields_when_constructed_then_kind_is_clarification(self):
        req = ClarificationRequest(
            question="which file?",
            agent_name="coder",
            invocation=0,
            turn=1,
        )
        assert req.kind is ResponderKind.CLARIFICATION
        assert req.question == "which file?"
        assert req.options == []
        assert req.agent_name == "coder"
        assert req.invocation == 0
        assert req.turn == 1

    def test_given_options_when_constructed_then_options_preserved(self):
        req = ClarificationRequest(
            question="pick",
            options=["a", "b"],
            agent_name="coder",
            invocation=0,
            turn=0,
        )
        assert req.options == ["a", "b"]

    def test_given_empty_question_when_constructed_then_raises(self):
        with pytest.raises(ValidationError):
            ClarificationRequest(
                question="",
                agent_name="coder",
                invocation=0,
                turn=0,
            )

    def test_given_empty_agent_name_when_constructed_then_raises(self):
        with pytest.raises(ValidationError):
            ClarificationRequest(
                question="q",
                agent_name="",
                invocation=0,
                turn=0,
            )

    def test_given_negative_turn_when_constructed_then_raises(self):
        with pytest.raises(ValidationError):
            ClarificationRequest(
                question="q",
                agent_name="coder",
                invocation=0,
                turn=-1,
            )

    def test_given_negative_invocation_when_constructed_then_raises(self):
        with pytest.raises(ValidationError):
            ClarificationRequest(
                question="q",
                agent_name="coder",
                invocation=-1,
                turn=0,
            )

    def test_given_wrong_type_when_constructed_then_raises(self):
        with pytest.raises(ValidationError):
            ClarificationRequest(
                question="q",
                agent_name="coder",
                invocation="zero",  # type: ignore[arg-type]
                turn=0,
            )

    def test_round_trip_serialization(self):
        req = ClarificationRequest(
            question="q",
            options=["a"],
            agent_name="coder",
            invocation=2,
            turn=3,
        )
        restored = ClarificationRequest.model_validate(req.model_dump())
        assert restored == req


class TestPermissionRequest:
    def test_given_required_fields_when_constructed_then_kind_is_permission(self):
        req = PermissionRequest(
            action_summary="write file",
            risk_level="medium",
            why_needed="needed for task",
            agent_name="coder",
            invocation=0,
            turn=1,
        )
        assert req.kind is ResponderKind.PERMISSION
        assert req.action_summary == "write file"
        assert req.risk_level == "medium"
        assert req.why_needed == "needed for task"
        assert req.agent_name == "coder"

    def test_given_empty_action_summary_when_constructed_then_raises(self):
        with pytest.raises(ValidationError):
            PermissionRequest(
                action_summary="",
                risk_level="low",
                why_needed="x",
                agent_name="coder",
                invocation=0,
                turn=0,
            )

    def test_given_negative_turn_when_constructed_then_raises(self):
        with pytest.raises(ValidationError):
            PermissionRequest(
                action_summary="write",
                risk_level="low",
                why_needed="x",
                agent_name="coder",
                invocation=0,
                turn=-1,
            )

    def test_round_trip_serialization(self):
        req = PermissionRequest(
            action_summary="write",
            risk_level="low",
            why_needed="x",
            agent_name="coder",
            invocation=0,
            turn=0,
        )
        restored = PermissionRequest.model_validate(req.model_dump())
        assert restored == req


class TestResponderRequestDiscriminator:
    def _adapter(self) -> TypeAdapter[ResponderRequest]:
        return TypeAdapter(ResponderRequest)

    def test_given_clarification_shaped_dict_when_validated_then_clarification_request(self):
        data = {
            "kind": "clarification",
            "question": "which file?",
            "agent_name": "coder",
            "invocation": 0,
            "turn": 1,
        }
        result = self._adapter().validate_python(data)
        assert isinstance(result, ClarificationRequest)
        assert result.question == "which file?"

    def test_given_permission_shaped_dict_when_validated_then_permission_request(self):
        data = {
            "kind": "permission",
            "action_summary": "write",
            "risk_level": "low",
            "why_needed": "x",
            "agent_name": "coder",
            "invocation": 0,
            "turn": 1,
        }
        result = self._adapter().validate_python(data)
        assert isinstance(result, PermissionRequest)
        assert result.action_summary == "write"

    def test_given_unknown_kind_when_validated_then_raises(self):
        data = {
            "kind": "bogus",
            "question": "q",
            "agent_name": "coder",
            "invocation": 0,
            "turn": 0,
        }
        with pytest.raises(ValidationError):
            self._adapter().validate_python(data)


class TestResponderResponse:
    def test_given_answer_when_constructed_then_stored(self):
        resp = ResponderResponse(answer="allow")
        assert resp.answer == "allow"

    def test_round_trip(self):
        resp = ResponderResponse(answer="use src/main.py")
        assert ResponderResponse.model_validate(resp.model_dump()) == resp


class TestResponderContext:
    def test_model_config_is_frozen(self):
        assert ResponderContext.model_config.get("frozen") is True

    def test_given_required_fields_when_constructed_then_frozen(self):
        ctx = ResponderContext(
            run_id="run-1",
            request_id="req-1",
            agent_name="coder",
            invocation=0,
            turn=1,
        )
        assert ctx.run_id == "run-1"
        assert ctx.request_id == "req-1"
        with pytest.raises(ValidationError):
            ctx.run_id = "mutated"  # type: ignore[misc]

    def test_given_empty_run_id_when_constructed_then_raises(self):
        with pytest.raises(ValidationError):
            ResponderContext(
                run_id="",
                request_id="req-1",
                agent_name="coder",
                invocation=0,
                turn=0,
            )

    def test_given_negative_turn_when_constructed_then_raises(self):
        with pytest.raises(ValidationError):
            ResponderContext(
                run_id="run-1",
                request_id="req-1",
                agent_name="coder",
                invocation=0,
                turn=-1,
            )


class TestBuildRequestFromOutcome:
    def test_given_clarification_outcome_when_built_then_returns_clarification_request(self):
        outcome = ClarificationOutcome(question="which file?", options=["a", "b"])
        req = build_request_from_outcome(outcome, agent_name="coder", invocation=2, turn=3)
        assert isinstance(req, ClarificationRequest)
        assert req.question == "which file?"
        assert req.options == ["a", "b"]
        assert req.agent_name == "coder"
        assert req.invocation == 2
        assert req.turn == 3

    def test_given_permission_outcome_when_built_then_returns_permission_request(self):
        outcome = PermissionOutcome(action="write", risk_level="medium", why_needed="x")
        req = build_request_from_outcome(outcome, agent_name="coder", invocation=0, turn=1)
        assert isinstance(req, PermissionRequest)
        assert req.action_summary == "write"
        assert req.risk_level == "medium"
        assert req.why_needed == "x"
        assert req.agent_name == "coder"
        assert req.invocation == 0
        assert req.turn == 1

    def test_given_clarification_outcome_options_are_copied_not_aliased(self):
        options = ["a", "b"]
        outcome = ClarificationOutcome(question="q", options=options)
        req = build_request_from_outcome(outcome, agent_name="coder", invocation=0, turn=0)
        assert isinstance(req, ClarificationRequest)
        assert req.options == ["a", "b"]
