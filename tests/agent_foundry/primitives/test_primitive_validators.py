"""Tests for primitive graph validators."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agent_foundry.primitives.errors import (
    InvalidPromptKeyError,
    PrimitiveValidationError,
    TypeMismatchError,
)
from agent_foundry.primitives.models import (
    Conditional,
    GateAction,
    Loop,
    Primitive,
    Retry,
    Sequence,
)
from agent_foundry.primitives.validators import validate_primitive

# -- Test fixtures --


class StateA(BaseModel):
    x: str


class StateB(BaseModel):
    y: int


class StateC(BaseModel):
    z: float


class GateState(BaseModel):
    should_block: bool
    escalation_context: str


class GateOutput(BaseModel):
    human_response: str


# ======================================================================
# Error Classes
# ======================================================================


class TestPrimitiveValidationError:
    def test_is_exception(self):
        err = PrimitiveValidationError("something broke")
        assert isinstance(err, Exception)
        assert str(err) == "something broke"


class TestTypeMismatchError:
    def test_carries_context(self):
        err = TypeMismatchError(
            message="output StateA does not match input StateB",
            expected=StateB,
            actual=StateA,
            position="Sequence step 0 -> step 1",
        )
        assert isinstance(err, PrimitiveValidationError)
        assert err.expected is StateB
        assert err.actual is StateA
        assert err.position == "Sequence step 0 -> step 1"
        assert "StateA" in str(err)


class TestInvalidPromptKeyError:
    def test_carries_context(self):
        err = InvalidPromptKeyError(
            message="prompt_key 'missing' not found",
            prompt_key="missing",
            available_fields=["should_block", "escalation_context"],
        )
        assert isinstance(err, PrimitiveValidationError)
        assert err.prompt_key == "missing"
        assert err.available_fields == ["should_block", "escalation_context"]


# ======================================================================
# Sequence Validation
# ======================================================================


class TestSequenceValidation:
    def test_valid_single_step(self):
        step = Primitive[StateA, StateB]()
        seq = Sequence[StateA, StateB](steps=[step])
        validate_primitive(seq)  # should not raise

    def test_valid_chain(self):
        s1 = Primitive[StateA, StateB]()
        s2 = Primitive[StateB, StateC]()
        seq = Sequence[StateA, StateC](steps=[s1, s2])
        validate_primitive(seq)  # should not raise

    def test_first_step_input_mismatch(self):
        step = Primitive[StateB, StateB]()
        seq = Sequence[StateA, StateB](steps=[step])
        with pytest.raises(TypeMismatchError, match="Sequence step 0 input"):
            validate_primitive(seq)

    def test_last_step_output_mismatch(self):
        step = Primitive[StateA, StateA]()
        seq = Sequence[StateA, StateB](steps=[step])
        with pytest.raises(TypeMismatchError, match="Sequence output"):
            validate_primitive(seq)

    def test_adjacent_step_mismatch(self):
        s1 = Primitive[StateA, StateB]()
        s2 = Primitive[StateC, StateC]()  # expects StateC fields, not available
        seq = Sequence[StateA, StateC](steps=[s1, s2])
        with pytest.raises(TypeMismatchError, match="Sequence step 1 input"):
            validate_primitive(seq)

    def test_recurses_into_steps(self):
        """A nested sequence with an internal mismatch is caught."""
        bad_inner = Primitive[StateC, StateC]()  # wrong input
        inner_seq = Sequence[StateA, StateC](steps=[bad_inner])
        outer_seq = Sequence[StateA, StateC](steps=[inner_seq])
        with pytest.raises(TypeMismatchError):
            validate_primitive(outer_seq)


# ======================================================================
# Loop Validation
# ======================================================================


class TestLoopValidation:
    def test_valid_loop_passes(self):
        body = Primitive[StateA, StateA]()
        loop = Loop[StateA, StateA](
            over=lambda s: [],
            item_key="item",
            body=body,
        )
        validate_primitive(loop)  # should not raise

    def test_recurses_into_body(self):
        """Errors inside the loop body are caught."""
        bad_step = Primitive[StateC, StateC]()
        inner_seq = Sequence[StateA, StateA](steps=[bad_step])
        loop = Loop[StateA, StateA](
            over=lambda s: [],
            item_key="item",
            body=inner_seq,
        )
        with pytest.raises(TypeMismatchError):
            validate_primitive(loop)


# ======================================================================
# Retry Validation
# ======================================================================


class TestRetryValidation:
    def test_valid_body(self):
        body = Primitive[StateA, StateA]()
        retry = Retry[StateA, StateA](
            max_attempts=2,
            until=lambda s: True,
            body=body,
        )
        validate_primitive(retry)  # should not raise

    def test_body_input_mismatch(self):
        body = Primitive[StateB, StateA]()
        retry = Retry[StateA, StateA](
            max_attempts=2,
            until=lambda s: True,
            body=body,
        )
        with pytest.raises(TypeMismatchError, match="Retry body input"):
            validate_primitive(retry)

    def test_body_output_mismatch(self):
        body = Primitive[StateA, StateB]()
        retry = Retry[StateA, StateA](
            max_attempts=2,
            until=lambda s: True,
            body=body,
        )
        with pytest.raises(TypeMismatchError, match="Retry body output"):
            validate_primitive(retry)

    def test_body_reentry_mismatch(self):
        """Body output must be compatible with body input for re-entry."""
        body = Primitive[StateA, StateB]()
        retry = Retry[StateA, StateB](
            max_attempts=2,
            until=lambda s: True,
            body=body,
        )
        with pytest.raises(TypeMismatchError, match="re-entry"):
            validate_primitive(retry)

    def test_body_reentry_valid_when_same_type(self):
        body = Primitive[StateA, StateA]()
        retry = Retry[StateA, StateA](
            max_attempts=2,
            until=lambda s: True,
            body=body,
        )
        validate_primitive(retry)  # should not raise

    def test_recurses_into_body(self):
        bad_step = Primitive[StateC, StateC]()
        inner_seq = Sequence[StateA, StateA](steps=[bad_step])
        retry = Retry[StateA, StateA](
            max_attempts=2,
            until=lambda s: True,
            body=inner_seq,
        )
        with pytest.raises(TypeMismatchError):
            validate_primitive(retry)


# ======================================================================
# Conditional Validation
# ======================================================================


class TestConditionalValidation:
    def test_valid_both_branches(self):
        then = Primitive[StateA, StateB]()
        else_ = Primitive[StateA, StateB]()
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=then,
            else_branch=else_,
        )
        validate_primitive(cond)  # should not raise

    def test_valid_no_else(self):
        """No else branch: all types must be identical (detour pattern)."""
        then = Primitive[StateA, StateA]()
        cond = Conditional[StateA, StateA](
            condition=lambda s: True,
            then_branch=then,
        )
        validate_primitive(cond)  # should not raise

    def test_no_else_input_output_mismatch(self):
        """No else branch but Conditional.I != Conditional.O — not a valid detour."""
        then = Primitive[StateA, StateB]()
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=then,
        )
        with pytest.raises(TypeMismatchError, match="no else_branch"):
            validate_primitive(cond)

    def test_no_else_then_output_mismatch(self):
        """No else branch but then_branch.O != Conditional.I — not a valid detour."""
        then = Primitive[StateA, StateB]()
        cond = Conditional[StateA, StateA](
            condition=lambda s: True,
            then_branch=then,
        )
        with pytest.raises(TypeMismatchError, match="then_branch output"):
            validate_primitive(cond)

    def test_then_input_mismatch(self):
        then = Primitive[StateC, StateB]()
        else_ = Primitive[StateA, StateB]()
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=then,
            else_branch=else_,
        )
        with pytest.raises(TypeMismatchError, match="then_branch input"):
            validate_primitive(cond)

    def test_then_output_mismatch(self):
        then = Primitive[StateA, StateC]()
        else_ = Primitive[StateA, StateB]()
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=then,
            else_branch=else_,
        )
        with pytest.raises(TypeMismatchError, match="then_branch output"):
            validate_primitive(cond)

    def test_else_input_mismatch(self):
        then = Primitive[StateA, StateB]()
        else_ = Primitive[StateC, StateB]()
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=then,
            else_branch=else_,
        )
        with pytest.raises(TypeMismatchError, match="else_branch input"):
            validate_primitive(cond)

    def test_else_output_mismatch(self):
        then = Primitive[StateA, StateB]()
        else_ = Primitive[StateA, StateC]()
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=then,
            else_branch=else_,
        )
        with pytest.raises(TypeMismatchError, match="else_branch output"):
            validate_primitive(cond)

    def test_recurses_into_then_branch(self):
        """Errors inside then_branch are caught (with else present)."""
        bad_step = Primitive[StateC, StateC]()
        bad_seq = Sequence[StateA, StateB](steps=[bad_step])
        good_else = Primitive[StateA, StateB]()
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=bad_seq,
            else_branch=good_else,
        )
        with pytest.raises(TypeMismatchError):
            validate_primitive(cond)

    def test_recurses_into_else_branch(self):
        """Errors inside else_branch are caught."""
        good_then = Primitive[StateA, StateB]()
        bad_step = Primitive[StateC, StateC]()
        bad_seq = Sequence[StateA, StateB](steps=[bad_step])
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=good_then,
            else_branch=bad_seq,
        )
        with pytest.raises(TypeMismatchError):
            validate_primitive(cond)

    def test_recurses_into_no_else_then_branch(self):
        """Errors inside then_branch are caught (no else, detour pattern)."""
        bad_step = Primitive[StateC, StateC]()
        bad_seq = Sequence[StateA, StateA](steps=[bad_step])
        cond = Conditional[StateA, StateA](
            condition=lambda s: True,
            then_branch=bad_seq,
        )
        with pytest.raises(TypeMismatchError):
            validate_primitive(cond)


# ======================================================================
# GateAction Validation
# ======================================================================


class TestGateActionValidation:
    def test_valid_prompt_key(self):
        gate = GateAction[GateState, GateOutput](
            interaction="human_stdin",
            prompt_key="escalation_context",
        )
        validate_primitive(gate)  # should not raise

    def test_invalid_prompt_key(self):
        gate = GateAction[GateState, GateOutput](
            interaction="human_stdin",
            prompt_key="nonexistent_field",
        )
        with pytest.raises(InvalidPromptKeyError) as exc_info:
            validate_primitive(gate)
        assert exc_info.value.prompt_key == "nonexistent_field"
        assert "should_block" in exc_info.value.available_fields
        assert "escalation_context" in exc_info.value.available_fields


# ======================================================================
# PrimitivePlan.validate() and Public API
# ======================================================================


class TestPrimitivePlanValidate:
    def test_valid_plan_passes(self):
        from agent_foundry.primitives.plan import PrimitivePlan

        s1 = Primitive[StateA, StateB]()
        s2 = Primitive[StateB, StateC]()
        seq = Sequence[StateA, StateC](steps=[s1, s2])
        plan = PrimitivePlan(root=seq)
        plan.validate()  # should not raise

    def test_invalid_plan_raises(self):
        from agent_foundry.primitives.plan import PrimitivePlan

        bad = Primitive[StateC, StateC]()
        seq = Sequence[StateA, StateB](steps=[bad])
        plan = PrimitivePlan(root=seq)
        with pytest.raises(TypeMismatchError):
            plan.validate()


class TestValidatorPublicAPI:
    def test_import_validate_primitive_from_package(self):
        from agent_foundry.primitives import validate_primitive

        assert validate_primitive is not None

    def test_import_errors_from_package(self):
        from agent_foundry.primitives import (
            InvalidPromptKeyError,
            PrimitiveValidationError,
            TypeMismatchError,
        )

        assert PrimitiveValidationError is not None
        assert TypeMismatchError is not None
        assert InvalidPromptKeyError is not None
