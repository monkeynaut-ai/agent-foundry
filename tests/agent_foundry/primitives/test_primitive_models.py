"""Tests for primitive models and common contract."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from agent_foundry.primitives.models import (
    Conditional,
    FunctionAction,
    GateAction,
    Loop,
    Primitive,
    Retry,
    Sequence,
    get_type_args,
)


class StubInput(BaseModel):
    value: str


class StubOutput(BaseModel):
    result: str


# ======================================================================
# Primitive Base
# ======================================================================


class TestPrimitiveBase:
    """Primitive base model is parameterized with input/output types."""

    def test_given_type_params_when_created_then_succeeds(self):
        p = Primitive[StubInput, StubOutput]()
        input_type, output_type = get_type_args(p)
        assert input_type is StubInput
        assert output_type is StubOutput

    def test_unparameterized_primitive_raises_at_construction(self):
        with pytest.raises(ValidationError, match="must be parameterized"):
            Primitive()


# -- Fixture models for Loop tests --


class ChangeSet(BaseModel):
    name: str
    steps: list[str]


class LoopInput(BaseModel):
    change_sets: list[ChangeSet]


class LoopOutput(BaseModel):
    change_sets: list[ChangeSet]


# -- Fixture models for Retry tests --


class RetryInput(BaseModel):
    findings: list[str]
    no_must_fix: bool


class RetryOutput(BaseModel):
    findings: list[str]
    no_must_fix: bool


# -- Fixture models for Conditional tests --


class CondInput(BaseModel):
    has_findings: bool


class CondOutput(BaseModel):
    handled: bool


# -- Fixture models for Gate tests --


class GateInput(BaseModel):
    must_fix_remain: bool
    escalation_context: str


class GateOutput(BaseModel):
    human_response: str


# -- Fixture models for Action tests --


class CommitInput(BaseModel):
    workspace_volume: str


class CommitOutput(BaseModel):
    commit_hash: str


def fake_commit(state: CommitInput) -> CommitOutput:
    return CommitOutput(commit_hash="abc123")


# ======================================================================
# Sequence
# ======================================================================


class TestSequence:
    """Sequence primitive executes steps in order."""

    def test_given_valid_steps_when_created_then_succeeds(self):
        inner = Primitive[StubInput, StubOutput]()
        seq = Sequence[StubInput, StubOutput](steps=[inner])
        assert len(seq.steps) == 1
        assert isinstance(seq.steps[0], Primitive)

    def test_given_multiple_steps_when_created_then_succeeds(self):
        a = Primitive[StubInput, StubOutput]()
        b = Primitive[StubInput, StubOutput]()
        c = Primitive[StubInput, StubOutput]()
        seq = Sequence[StubInput, StubOutput](steps=[a, b, c])
        assert len(seq.steps) == 3

    def test_given_empty_steps_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Sequence[StubInput, StubOutput](steps=[])

    def test_given_no_steps_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Sequence[StubInput, StubOutput]()

    def test_type_args_preserved(self):
        inner = Primitive[StubInput, StubOutput]()
        seq = Sequence[StubInput, StubOutput](steps=[inner])
        input_type, output_type = get_type_args(seq)
        assert input_type is StubInput
        assert output_type is StubOutput


# ======================================================================
# Loop
# ======================================================================


class TestLoop:
    """Loop primitive iterates over a collection in state."""

    def test_given_valid_config_when_created_then_succeeds(self):
        body = Primitive[StubInput, StubOutput]()
        loop = Loop[LoopInput, LoopOutput](
            over=lambda state: state.change_sets,
            item_key="current_change_set",
            body=body,
        )
        assert loop.item_key == "current_change_set"
        assert loop.max_iterations == 100

    def test_given_custom_max_iterations_when_created_then_stored(self):
        body = Primitive[StubInput, StubOutput]()
        loop = Loop[LoopInput, LoopOutput](
            over=lambda state: state.change_sets,
            item_key="current_change_set",
            body=body,
            max_iterations=50,
        )
        assert loop.max_iterations == 50

    def test_given_zero_max_iterations_when_created_then_raises(self):
        body = Primitive[StubInput, StubOutput]()
        with pytest.raises(ValidationError):
            Loop[LoopInput, LoopOutput](
                over=lambda state: state.change_sets,
                item_key="current_change_set",
                body=body,
                max_iterations=0,
            )

    def test_given_empty_item_key_when_created_then_raises(self):
        body = Primitive[StubInput, StubOutput]()
        with pytest.raises(ValidationError):
            Loop[LoopInput, LoopOutput](
                over=lambda state: state.change_sets,
                item_key="",
                body=body,
            )

    def test_given_missing_over_when_created_then_raises(self):
        body = Primitive[StubInput, StubOutput]()
        with pytest.raises(ValidationError):
            Loop[LoopInput, LoopOutput](
                item_key="item",
                body=body,
            )

    def test_over_callable_is_invocable(self):
        body = Primitive[StubInput, StubOutput]()
        loop = Loop[LoopInput, LoopOutput](
            over=lambda state: state.change_sets,
            item_key="current_change_set",
            body=body,
        )
        state = LoopInput(change_sets=[ChangeSet(name="cs1", steps=["s1"])])
        result = loop.over(state)
        assert len(result) == 1
        assert result[0].name == "cs1"


# ======================================================================
# Retry
# ======================================================================


class TestRetry:
    """Retry primitive repeats body until condition met or exhausted."""

    def test_given_valid_config_when_created_then_succeeds(self):
        body = Primitive[StubInput, StubOutput]()
        retry = Retry[RetryInput, RetryOutput](
            max_attempts=2,
            until=lambda state: state.no_must_fix,
            body=body,
        )
        assert retry.max_attempts == 2

    def test_until_callable_is_invocable(self):
        body = Primitive[StubInput, StubOutput]()
        retry = Retry[RetryInput, RetryOutput](
            max_attempts=2,
            until=lambda state: state.no_must_fix,
            body=body,
        )
        state = RetryInput(findings=[], no_must_fix=True)
        assert retry.until(state) is True

    def test_given_zero_max_attempts_when_created_then_raises(self):
        body = Primitive[StubInput, StubOutput]()
        with pytest.raises(ValidationError):
            Retry[RetryInput, RetryOutput](
                max_attempts=0,
                until=lambda state: state.no_must_fix,
                body=body,
            )


# ======================================================================
# Conditional
# ======================================================================


class TestConditional:
    """Conditional primitive branches based on state."""

    def test_given_both_branches_when_created_then_succeeds(self):
        then = Primitive[StubInput, StubOutput]()
        else_ = Primitive[StubInput, StubOutput]()
        cond = Conditional[CondInput, CondOutput](
            condition=lambda state: state.has_findings,
            then_branch=then,
            else_branch=else_,
        )
        assert isinstance(cond.then_branch, Primitive)
        assert isinstance(cond.else_branch, Primitive)

    def test_given_no_else_branch_when_created_then_none(self):
        then = Primitive[StubInput, StubOutput]()
        cond = Conditional[CondInput, CondOutput](
            condition=lambda state: state.has_findings,
            then_branch=then,
        )
        assert cond.else_branch is None

    def test_condition_callable_is_invocable(self):
        then = Primitive[StubInput, StubOutput]()
        cond = Conditional[CondInput, CondOutput](
            condition=lambda state: state.has_findings,
            then_branch=then,
        )
        state = CondInput(has_findings=True)
        assert cond.condition(state) is True

    def test_given_missing_then_branch_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Conditional[CondInput, CondOutput](
                condition=lambda state: state.has_findings,
            )

    def test_given_missing_condition_when_created_then_raises(self):
        then = Primitive[StubInput, StubOutput]()
        with pytest.raises(ValidationError):
            Conditional[CondInput, CondOutput](
                then_branch=then,
            )


# ======================================================================
# Gate
# ======================================================================


class TestGateAction:
    """GateAction always blocks when reached — no condition field."""

    def test_given_valid_config_when_created_then_succeeds(self):
        gate = GateAction[GateInput, GateOutput](
            interaction="human_stdin",
            prompt_key="escalation_context",
        )
        assert gate.interaction == "human_stdin"
        assert gate.prompt_key == "escalation_context"

    def test_given_missing_interaction_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            GateAction[GateInput, GateOutput](
                prompt_key="escalation_context",
            )

    def test_given_missing_prompt_key_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            GateAction[GateInput, GateOutput](
                interaction="human_stdin",
            )

    def test_given_empty_interaction_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            GateAction[GateInput, GateOutput](
                interaction="",
                prompt_key="escalation_context",
            )


# ======================================================================
# Action
# ======================================================================


class TestFunctionAction:
    """FunctionAction wraps a synchronous, in-process function."""

    def test_given_valid_function_when_created_then_succeeds(self):
        action = FunctionAction[CommitInput, CommitOutput](function=fake_commit)
        assert callable(action.function)

    def test_function_is_invocable(self):
        action = FunctionAction[CommitInput, CommitOutput](function=fake_commit)
        result = action.function(CommitInput(workspace_volume="vol-1"))
        assert result.commit_hash == "abc123"

    def test_given_lambda_function_when_created_then_succeeds(self):
        action = FunctionAction[StubInput, StubOutput](
            function=lambda state: StubOutput(result="done"),
        )
        result = action.function(StubInput(value="test"))
        assert result.result == "done"

    def test_given_missing_function_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            FunctionAction[CommitInput, CommitOutput]()


# ======================================================================
# Recursive Nesting
# ======================================================================


class TestRecursiveNesting:
    """Primitives can be nested recursively via direct object references."""

    def test_sequence_containing_loop(self):
        body = Primitive[StubInput, StubOutput]()
        loop = Loop[LoopInput, LoopOutput](
            over=lambda state: state.change_sets,
            item_key="current",
            body=body,
        )
        seq = Sequence[StubInput, StubOutput](steps=[loop])
        assert isinstance(seq.steps[0], Loop)

    def test_retry_containing_sequence(self):
        a = Primitive[StubInput, StubOutput]()
        b = Primitive[StubInput, StubOutput]()
        inner_seq = Sequence[StubInput, StubOutput](steps=[a, b])
        retry = Retry[RetryInput, RetryOutput](
            max_attempts=2,
            until=lambda state: state.no_must_fix,
            body=inner_seq,
        )
        assert isinstance(retry.body, Sequence)

    def test_sequence_containing_conditional_containing_loop(self):
        body = Primitive[StubInput, StubOutput]()
        loop = Loop[LoopInput, LoopOutput](
            over=lambda state: state.change_sets,
            item_key="current",
            body=body,
        )
        cond = Conditional[CondInput, CondOutput](
            condition=lambda state: state.has_findings,
            then_branch=loop,
        )
        seq = Sequence[StubInput, StubOutput](steps=[cond])
        assert isinstance(seq.steps[0], Conditional)
        assert isinstance(seq.steps[0].then_branch, Loop)


# ======================================================================
# Public API
# ======================================================================


class TestPublicAPI:
    """All primitives are importable from the package."""

    def test_import_from_package(self):
        from agent_foundry.primitives import (
            Conditional,
            FunctionAction,
            GateAction,
            Loop,
            Primitive,
            PrimitivePlan,
            Retry,
            Sequence,
        )

        assert Primitive is not None
        assert Sequence is not None
        assert Loop is not None
        assert Retry is not None
        assert Conditional is not None
        assert FunctionAction is not None
        assert GateAction is not None
        assert PrimitivePlan is not None

    def test_agent_action_importable_from_package(self):
        from agent_foundry.primitives import AgentAction

        assert AgentAction is not None

    def test_container_reuse_policy_importable_from_package(self):
        from agent_foundry.primitives import ContainerReusePolicy

        assert ContainerReusePolicy is not None

    def test_response_channels_not_exported_from_package(self):
        """Task A.2 removed response channel types from the primitives surface."""
        import agent_foundry.primitives as primitives

        assert not hasattr(primitives, "StructuredOutputChannel")
        assert not hasattr(primitives, "FileCollectionChannel")
        assert not hasattr(primitives, "ResponseChannel")
        assert not hasattr(primitives, "ResponseChannelKind")
