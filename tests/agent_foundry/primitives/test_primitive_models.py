"""Tests for primitive models and common contract."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from agent_foundry.primitives.models import (
    Action,
    Conditional,
    Gate,
    Loop,
    Primitive,
    Retry,
    Sequence,
)


class StubInput(BaseModel):
    value: str


class StubOutput(BaseModel):
    result: str


class TestPrimitiveBase:
    """Primitive base model enforces input and output."""

    def test_given_valid_fields_when_created_then_succeeds(self):
        p = Primitive(input=StubInput, output=StubOutput)
        assert p.input is StubInput
        assert p.output is StubOutput

    def test_given_missing_input_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Primitive(output=StubOutput)

    def test_given_missing_output_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Primitive(input=StubInput)

    def test_given_non_basemodel_input_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Primitive(input=str, output=StubOutput)

    def test_given_non_basemodel_output_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Primitive(input=StubInput, output=str)


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
        inner = Primitive(input=StubInput, output=StubOutput)
        seq = Sequence(
            input=StubInput,
            output=StubOutput,
            steps=[inner],
        )
        assert len(seq.steps) == 1
        assert isinstance(seq.steps[0], Primitive)

    def test_given_multiple_steps_when_created_then_succeeds(self):
        a = Primitive(input=StubInput, output=StubOutput)
        b = Primitive(input=StubInput, output=StubOutput)
        c = Primitive(input=StubInput, output=StubOutput)
        seq = Sequence(
            input=StubInput,
            output=StubOutput,
            steps=[a, b, c],
        )
        assert len(seq.steps) == 3

    def test_given_empty_steps_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Sequence(
                input=StubInput,
                output=StubOutput,
                steps=[],
            )

    def test_given_no_steps_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Sequence(input=StubInput, output=StubOutput)


# ======================================================================
# Loop
# ======================================================================


class TestLoop:
    """Loop primitive iterates over a collection in state."""

    def test_given_valid_config_when_created_then_succeeds(self):
        body = Primitive(input=StubInput, output=StubOutput)
        loop = Loop(
            input=LoopInput,
            output=LoopOutput,
            over=lambda state: state.change_sets,
            item_key="current_change_set",
            body=body,
        )
        assert loop.item_key == "current_change_set"
        assert loop.max_iterations == 100

    def test_given_custom_max_iterations_when_created_then_stored(self):
        body = Primitive(input=StubInput, output=StubOutput)
        loop = Loop(
            input=LoopInput,
            output=LoopOutput,
            over=lambda state: state.change_sets,
            item_key="current_change_set",
            body=body,
            max_iterations=50,
        )
        assert loop.max_iterations == 50

    def test_given_zero_max_iterations_when_created_then_raises(self):
        body = Primitive(input=StubInput, output=StubOutput)
        with pytest.raises(ValidationError):
            Loop(
                input=LoopInput,
                output=LoopOutput,
                over=lambda state: state.change_sets,
                item_key="current_change_set",
                body=body,
                max_iterations=0,
            )

    def test_given_empty_item_key_when_created_then_raises(self):
        body = Primitive(input=StubInput, output=StubOutput)
        with pytest.raises(ValidationError):
            Loop(
                input=LoopInput,
                output=LoopOutput,
                over=lambda state: state.change_sets,
                item_key="",
                body=body,
            )

    def test_given_missing_over_when_created_then_raises(self):
        body = Primitive(input=StubInput, output=StubOutput)
        with pytest.raises(ValidationError):
            Loop(
                input=LoopInput,
                output=LoopOutput,
                item_key="item",
                body=body,
            )

    def test_over_callable_is_invocable(self):
        body = Primitive(input=StubInput, output=StubOutput)
        loop = Loop(
            input=LoopInput,
            output=LoopOutput,
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
        body = Primitive(input=StubInput, output=StubOutput)
        retry = Retry(
            input=RetryInput,
            output=RetryOutput,
            max_attempts=2,
            until=lambda state: state.no_must_fix,
            body=body,
            on_exhausted="escalate",
        )
        assert retry.max_attempts == 2
        assert retry.on_exhausted == "escalate"

    def test_until_callable_is_invocable(self):
        body = Primitive(input=StubInput, output=StubOutput)
        retry = Retry(
            input=RetryInput,
            output=RetryOutput,
            max_attempts=2,
            until=lambda state: state.no_must_fix,
            body=body,
            on_exhausted="escalate",
        )
        state = RetryInput(findings=[], no_must_fix=True)
        assert retry.until(state) is True

    def test_given_zero_max_attempts_when_created_then_raises(self):
        body = Primitive(input=StubInput, output=StubOutput)
        with pytest.raises(ValidationError):
            Retry(
                input=RetryInput,
                output=RetryOutput,
                max_attempts=0,
                until=lambda state: state.no_must_fix,
                body=body,
                on_exhausted="escalate",
            )

    def test_given_missing_on_exhausted_when_created_then_raises(self):
        body = Primitive(input=StubInput, output=StubOutput)
        with pytest.raises(ValidationError):
            Retry(
                input=RetryInput,
                output=RetryOutput,
                max_attempts=2,
                until=lambda state: state.no_must_fix,
                body=body,
            )


# ======================================================================
# Conditional
# ======================================================================


class TestConditional:
    """Conditional primitive branches based on state."""

    def test_given_both_branches_when_created_then_succeeds(self):
        then = Primitive(input=StubInput, output=StubOutput)
        else_ = Primitive(input=StubInput, output=StubOutput)
        cond = Conditional(
            input=CondInput,
            output=CondOutput,
            condition=lambda state: state.has_findings,
            then_branch=then,
            else_branch=else_,
        )
        assert isinstance(cond.then_branch, Primitive)
        assert isinstance(cond.else_branch, Primitive)

    def test_given_no_else_branch_when_created_then_none(self):
        then = Primitive(input=StubInput, output=StubOutput)
        cond = Conditional(
            input=CondInput,
            output=CondOutput,
            condition=lambda state: state.has_findings,
            then_branch=then,
        )
        assert cond.else_branch is None

    def test_condition_callable_is_invocable(self):
        then = Primitive(input=StubInput, output=StubOutput)
        cond = Conditional(
            input=CondInput,
            output=CondOutput,
            condition=lambda state: state.has_findings,
            then_branch=then,
        )
        state = CondInput(has_findings=True)
        assert cond.condition(state) is True

    def test_given_missing_then_branch_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Conditional(
                input=CondInput,
                output=CondOutput,
                condition=lambda state: state.has_findings,
            )

    def test_given_missing_condition_when_created_then_raises(self):
        then = Primitive(input=StubInput, output=StubOutput)
        with pytest.raises(ValidationError):
            Conditional(
                input=CondInput,
                output=CondOutput,
                then_branch=then,
            )


# ======================================================================
# Gate
# ======================================================================


class TestGate:
    """Gate primitive blocks execution until external input."""

    def test_given_valid_config_when_created_then_succeeds(self):
        gate = Gate(
            input=GateInput,
            output=GateOutput,
            condition=lambda state: state.must_fix_remain,
            interaction="human_stdin",
            prompt_key="escalation_context",
        )
        assert gate.interaction == "human_stdin"
        assert gate.prompt_key == "escalation_context"

    def test_condition_callable_is_invocable(self):
        gate = Gate(
            input=GateInput,
            output=GateOutput,
            condition=lambda state: state.must_fix_remain,
            interaction="human_stdin",
            prompt_key="escalation_context",
        )
        state = GateInput(must_fix_remain=True, escalation_context="help")
        assert gate.condition(state) is True

    def test_given_false_condition_gate_is_skippable(self):
        gate = Gate(
            input=GateInput,
            output=GateOutput,
            condition=lambda state: state.must_fix_remain,
            interaction="human_stdin",
            prompt_key="escalation_context",
        )
        state = GateInput(must_fix_remain=False, escalation_context="")
        assert gate.condition(state) is False

    def test_given_missing_interaction_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Gate(
                input=GateInput,
                output=GateOutput,
                condition=lambda state: state.must_fix_remain,
                prompt_key="escalation_context",
            )

    def test_given_missing_prompt_key_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Gate(
                input=GateInput,
                output=GateOutput,
                condition=lambda state: state.must_fix_remain,
                interaction="human_stdin",
            )

    def test_given_empty_interaction_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Gate(
                input=GateInput,
                output=GateOutput,
                condition=lambda state: state.must_fix_remain,
                interaction="",
                prompt_key="escalation_context",
            )


# ======================================================================
# Action
# ======================================================================


class TestAction:
    """Action primitive wraps a deterministic, non-AI function."""

    def test_given_valid_function_when_created_then_succeeds(self):
        action = Action(
            input=CommitInput,
            output=CommitOutput,
            function=fake_commit,
        )
        assert callable(action.function)

    def test_function_is_invocable(self):
        action = Action(
            input=CommitInput,
            output=CommitOutput,
            function=fake_commit,
        )
        result = action.function(CommitInput(workspace_volume="vol-1"))
        assert result.commit_hash == "abc123"

    def test_given_lambda_function_when_created_then_succeeds(self):
        action = Action(
            input=StubInput,
            output=StubOutput,
            function=lambda state: StubOutput(result="done"),
        )
        result = action.function(StubInput(value="test"))
        assert result.result == "done"

    def test_given_missing_function_when_created_then_raises(self):
        with pytest.raises(ValidationError):
            Action(
                input=CommitInput,
                output=CommitOutput,
            )


# ======================================================================
# Recursive Nesting
# ======================================================================


class TestRecursiveNesting:
    """Primitives can be nested recursively via direct object references."""

    def test_sequence_containing_loop(self):
        body = Primitive(input=StubInput, output=StubOutput)
        loop = Loop(
            input=LoopInput,
            output=LoopOutput,
            over=lambda state: state.change_sets,
            item_key="current",
            body=body,
        )
        seq = Sequence(
            input=StubInput,
            output=StubOutput,
            steps=[loop],
        )
        assert isinstance(seq.steps[0], Loop)

    def test_retry_containing_sequence(self):
        a = Primitive(input=StubInput, output=StubOutput)
        b = Primitive(input=StubInput, output=StubOutput)
        inner_seq = Sequence(
            input=StubInput,
            output=StubOutput,
            steps=[a, b],
        )
        retry = Retry(
            input=RetryInput,
            output=RetryOutput,
            max_attempts=2,
            until=lambda state: state.no_must_fix,
            body=inner_seq,
            on_exhausted="escalate",
        )
        assert isinstance(retry.body, Sequence)

    def test_sequence_containing_conditional_containing_loop(self):
        body = Primitive(input=StubInput, output=StubOutput)
        loop = Loop(
            input=LoopInput,
            output=LoopOutput,
            over=lambda state: state.change_sets,
            item_key="current",
            body=body,
        )
        cond = Conditional(
            input=CondInput,
            output=CondOutput,
            condition=lambda state: state.has_findings,
            then_branch=loop,
        )
        seq = Sequence(
            input=StubInput,
            output=StubOutput,
            steps=[cond],
        )
        assert isinstance(seq.steps[0], Conditional)
        assert isinstance(seq.steps[0].then_branch, Loop)


# ======================================================================
# Public API
# ======================================================================


class TestPublicAPI:
    """All primitives are importable from the package."""

    def test_import_from_package(self):
        from agent_foundry.primitives import (
            Action,
            Conditional,
            Gate,
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
        assert Gate is not None
        assert Action is not None
        assert PrimitivePlan is not None
