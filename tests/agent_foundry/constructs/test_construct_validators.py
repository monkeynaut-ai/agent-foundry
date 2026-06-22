"""Tests for construct graph validators."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agent_foundry.constructs.errors import (
    ConstructValidationError,
    InvalidPromptKeyError,
    TypeMismatchError,
    UnregisteredConstructError,
)
from agent_foundry.constructs.models import (
    AgentAction,
    Conditional,
    Construct,
    ContainerReusePolicy,
    FunctionAction,
    GateAction,
    Loop,
    Retry,
    Sequence,
)
from agent_foundry.constructs.validators import register_validator, validate_construct

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
# Validator registry
# ======================================================================


class _RegInput(BaseModel):
    value: str


class _RegOutput(BaseModel):
    result: str


class TestValidatorRegistry:
    """Validator dispatch uses a registry keyed by construct type."""

    def test_unknown_construct_type_raises(self):
        class MyCustomConstruct[I: BaseModel, O: BaseModel](Construct[I, O]):
            def child_specs(self) -> list[tuple[Construct, str]]:
                return []

        prim = MyCustomConstruct[_RegInput, _RegOutput]()
        with pytest.raises(UnregisteredConstructError, match="MyCustomConstruct"):
            validate_construct(prim)

    def test_registering_validator_allows_validation(self):
        class MyCustomConstruct2[I: BaseModel, O: BaseModel](Construct[I, O]):
            def child_specs(self) -> list[tuple[Construct, str]]:
                return []

        calls: list[object] = []

        def _my_validator(prim):
            calls.append(prim)

        register_validator(MyCustomConstruct2, _my_validator)

        prim = MyCustomConstruct2[_RegInput, _RegOutput]()
        validate_construct(prim)
        assert len(calls) == 1
        assert calls[0] is prim

    def test_registry_walks_mro_for_subclasses(self):
        class ParentPrim[I: BaseModel, O: BaseModel](Construct[I, O]):
            def child_specs(self) -> list[tuple[Construct, str]]:
                return []

        class ChildPrim[I: BaseModel, O: BaseModel](ParentPrim[I, O]):
            pass

        calls: list[str] = []

        def _parent_validator(prim):
            calls.append("parent")

        register_validator(ParentPrim, _parent_validator)

        child = ChildPrim[_RegInput, _RegOutput]()
        validate_construct(child)
        assert calls == ["parent"]

    def test_dispatcher_recurses_via_child_specs(self):
        """The dispatcher walks child_specs after the per-type validator, so a
        composite's children are validated through the shared seam — even for a
        custom composite whose own validator does not recurse."""
        visited: list[Construct] = []

        class _Child[I: BaseModel, O: BaseModel](Construct[I, O]):
            def child_specs(self) -> list[tuple[Construct, str]]:
                return []

        class _Parent[I: BaseModel, O: BaseModel](Construct[I, O]):
            inner: Construct

            def child_specs(self) -> list[tuple[Construct, str]]:
                return [(self.inner, "inner")]

        register_validator(_Child, lambda p: visited.append(p))
        register_validator(_Parent, lambda p: visited.append(p))

        child = _Child[_RegInput, _RegOutput]()
        parent = _Parent[_RegInput, _RegOutput](inner=child)
        validate_construct(parent)

        assert visited == [parent, child]

    def test_duplicate_registration_raises(self):
        """Re-registering for the same type is a footgun; raise instead of clobbering."""

        class DuplicatePrim[I: BaseModel, O: BaseModel](Construct[I, O]):
            def child_specs(self) -> list[tuple[Construct, str]]:
                return []

        def _first(prim):
            pass

        def _second(prim):
            pass

        register_validator(DuplicatePrim, _first)
        with pytest.raises(ValueError, match="DuplicatePrim"):
            register_validator(DuplicatePrim, _second)


# ======================================================================
# Error Classes
# ======================================================================


class TestConstructValidationError:
    def test_is_exception(self):
        err = ConstructValidationError("something broke")
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
        assert isinstance(err, ConstructValidationError)
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
        assert isinstance(err, ConstructValidationError)
        assert err.prompt_key == "missing"
        assert err.available_fields == ["should_block", "escalation_context"]


# ======================================================================
# Sequence Validation
# ======================================================================


class TestSequenceValidation:
    def test_valid_single_step(self):
        step = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        seq = Sequence[StateA, StateB](steps=[step])
        validate_construct(seq)  # should not raise

    def test_valid_chain(self):
        s1 = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        s2 = FunctionAction[StateB, StateC](function=lambda s: StateC.model_construct())
        seq = Sequence[StateA, StateC](steps=[s1, s2])
        validate_construct(seq)  # should not raise

    def test_first_step_input_mismatch(self):
        step = FunctionAction[StateB, StateB](function=lambda s: s)
        seq = Sequence[StateA, StateB](steps=[step])
        with pytest.raises(TypeMismatchError, match="Sequence step 0 input"):
            validate_construct(seq)

    def test_last_step_output_mismatch(self):
        step = FunctionAction[StateA, StateA](function=lambda s: s)
        seq = Sequence[StateA, StateB](steps=[step])
        with pytest.raises(TypeMismatchError, match="Sequence output"):
            validate_construct(seq)

    def test_adjacent_step_mismatch(self):
        s1 = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        s2 = FunctionAction[StateC, StateC](function=lambda s: s)
        seq = Sequence[StateA, StateC](steps=[s1, s2])
        with pytest.raises(TypeMismatchError, match="Sequence step 1 input"):
            validate_construct(seq)

    def test_recurses_into_steps(self):
        """A nested sequence with an internal mismatch is caught."""
        bad_inner = FunctionAction[StateC, StateC](function=lambda s: s)
        inner_seq = Sequence[StateA, StateC](steps=[bad_inner])
        outer_seq = Sequence[StateA, StateC](steps=[inner_seq])
        with pytest.raises(TypeMismatchError):
            validate_construct(outer_seq)


# ======================================================================
# Loop Validation
# ======================================================================


class TestLoopValidation:
    def test_valid_loop_passes(self):
        body = FunctionAction[StateA, StateA](function=lambda s: s)
        loop = Loop[StateA, StateA](
            over=lambda s: [],
            item_key="item",
            body=body,
        )
        validate_construct(loop)  # should not raise

    def test_recurses_into_body(self):
        """Errors inside the loop body are caught."""
        bad_step = FunctionAction[StateC, StateC](function=lambda s: s)
        inner_seq = Sequence[StateA, StateA](steps=[bad_step])
        loop = Loop[StateA, StateA](
            over=lambda s: [],
            item_key="item",
            body=inner_seq,
        )
        with pytest.raises(TypeMismatchError):
            validate_construct(loop)


# ======================================================================
# Retry Validation
# ======================================================================


class TestRetryValidation:
    def test_valid_body(self):
        body = FunctionAction[StateA, StateA](function=lambda s: s)
        retry = Retry[StateA, StateA](
            max_attempts=2,
            until=lambda s: True,
            body=body,
        )
        validate_construct(retry)  # should not raise

    def test_body_input_mismatch(self):
        body = FunctionAction[StateB, StateA](function=lambda s: StateA.model_construct())
        retry = Retry[StateA, StateA](
            max_attempts=2,
            until=lambda s: True,
            body=body,
        )
        with pytest.raises(TypeMismatchError, match="Retry body input"):
            validate_construct(retry)

    def test_body_output_mismatch(self):
        body = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        retry = Retry[StateA, StateA](
            max_attempts=2,
            until=lambda s: True,
            body=body,
        )
        with pytest.raises(TypeMismatchError, match="Retry body output"):
            validate_construct(retry)

    def test_body_reentry_mismatch(self):
        """Body output must be compatible with body input for re-entry."""
        body = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        retry = Retry[StateA, StateB](
            max_attempts=2,
            until=lambda s: True,
            body=body,
        )
        with pytest.raises(TypeMismatchError, match="re-entry"):
            validate_construct(retry)

    def test_body_reentry_valid_when_same_type(self):
        body = FunctionAction[StateA, StateA](function=lambda s: s)
        retry = Retry[StateA, StateA](
            max_attempts=2,
            until=lambda s: True,
            body=body,
        )
        validate_construct(retry)  # should not raise

    def test_recurses_into_body(self):
        bad_step = FunctionAction[StateC, StateC](function=lambda s: s)
        inner_seq = Sequence[StateA, StateA](steps=[bad_step])
        retry = Retry[StateA, StateA](
            max_attempts=2,
            until=lambda s: True,
            body=inner_seq,
        )
        with pytest.raises(TypeMismatchError):
            validate_construct(retry)


class _ResolverState(BaseModel):
    n: int = 0
    verdict: str = ""


def _resolver_body():
    return FunctionAction[_ResolverState, _ResolverState](
        function=lambda s: _ResolverState(n=s.n + 1)
    )


class TestRetryResolverValidation:
    def test_validate_retry_with_function_resolver_ok(self):
        r = Retry[_ResolverState, _ResolverState](
            max_attempts=1,
            until=lambda s: False,
            body=_resolver_body(),
            on_max_attempts_resolver=FunctionAction[_ResolverState, _ResolverState](
                function=lambda s: s
            ),
        )
        validate_construct(r)  # no raise

    def test_validate_retry_resolver_field_not_available(self):
        class Extra(BaseModel):
            n: int = 0
            unknown: str = ""

        r = Retry[_ResolverState, _ResolverState](
            max_attempts=1,
            until=lambda s: False,
            body=_resolver_body(),
            on_max_attempts_resolver=FunctionAction[Extra, _ResolverState](
                function=lambda e: _ResolverState()
            ),
        )
        with pytest.raises(TypeMismatchError, match="resolver input"):
            validate_construct(r)

    def test_validate_retry_recurses_into_gate_resolver(self):
        bad_gate = GateAction[_ResolverState, _ResolverState](
            interaction="stdin", prompt_key="not_a_field"
        )
        r = Retry[_ResolverState, _ResolverState](
            max_attempts=1,
            until=lambda s: False,
            body=_resolver_body(),
            on_max_attempts_resolver=bad_gate,
        )
        with pytest.raises(InvalidPromptKeyError):
            validate_construct(r)

    def test_validate_retry_no_resolver_unchanged(self):
        r = Retry[_ResolverState, _ResolverState](
            max_attempts=2,
            until=lambda s: s.n >= 2,
            body=_resolver_body(),
        )
        validate_construct(r)  # existing behaviour, no raise

    def test_validate_retry_resolver_declares_well_known_metadata_ok(self):
        """A resolver may declare the exact well-known metadata field names; the
        compiler supplies them, so they pass availability validation."""

        class MetaIn(BaseModel):
            n: int = 0
            exhaustion_reason: str = ""
            attempt_failures: list = []

        r = Retry[_ResolverState, _ResolverState](
            max_attempts=1,
            until=lambda s: False,
            body=_resolver_body(),
            on_max_attempts_resolver=FunctionAction[MetaIn, _ResolverState](
                function=lambda m: _ResolverState()
            ),
        )
        validate_construct(r)  # no raise

    def test_validate_retry_resolver_bogus_metadata_like_field_still_fails(self):
        """A field that merely resembles a metadata channel but is neither in
        retry_in nor an exact well-known name still fails availability — closing
        the open-ended-suffix footgun."""

        class BogusIn(BaseModel):
            n: int = 0
            wrongprefix__exhaustion_reason: str = ""

        r = Retry[_ResolverState, _ResolverState](
            max_attempts=1,
            until=lambda s: False,
            body=_resolver_body(),
            on_max_attempts_resolver=FunctionAction[BogusIn, _ResolverState](
                function=lambda m: _ResolverState()
            ),
        )
        with pytest.raises(TypeMismatchError, match="resolver input"):
            validate_construct(r)


# ======================================================================
# Conditional Validation
# ======================================================================


class TestConditionalValidation:
    def test_valid_both_branches(self):
        then = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        else_ = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=then,
            else_branch=else_,
        )
        validate_construct(cond)  # should not raise

    def test_valid_no_else(self):
        """No else branch: all types must be identical (detour pattern)."""
        then = FunctionAction[StateA, StateA](function=lambda s: s)
        cond = Conditional[StateA, StateA](
            condition=lambda s: True,
            then_branch=then,
        )
        validate_construct(cond)  # should not raise

    def test_no_else_input_output_mismatch(self):
        """No else branch but Conditional.I != Conditional.O — not a valid detour."""
        then = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=then,
        )
        with pytest.raises(TypeMismatchError, match="no else_branch"):
            validate_construct(cond)

    def test_no_else_then_output_mismatch(self):
        """No else branch but then_branch.O != Conditional.I — not a valid detour."""
        then = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        cond = Conditional[StateA, StateA](
            condition=lambda s: True,
            then_branch=then,
        )
        with pytest.raises(TypeMismatchError, match="then_branch output"):
            validate_construct(cond)

    def test_then_input_mismatch(self):
        then = FunctionAction[StateC, StateB](function=lambda s: StateB.model_construct())
        else_ = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=then,
            else_branch=else_,
        )
        with pytest.raises(TypeMismatchError, match="then_branch input"):
            validate_construct(cond)

    def test_then_output_mismatch(self):
        then = FunctionAction[StateA, StateC](function=lambda s: StateC.model_construct())
        else_ = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=then,
            else_branch=else_,
        )
        with pytest.raises(TypeMismatchError, match="then_branch output"):
            validate_construct(cond)

    def test_else_input_mismatch(self):
        then = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        else_ = FunctionAction[StateC, StateB](function=lambda s: StateB.model_construct())
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=then,
            else_branch=else_,
        )
        with pytest.raises(TypeMismatchError, match="else_branch input"):
            validate_construct(cond)

    def test_else_output_mismatch(self):
        then = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        else_ = FunctionAction[StateA, StateC](function=lambda s: StateC.model_construct())
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=then,
            else_branch=else_,
        )
        with pytest.raises(TypeMismatchError, match="else_branch output"):
            validate_construct(cond)

    def test_recurses_into_then_branch(self):
        """Errors inside then_branch are caught (with else present)."""
        bad_step = FunctionAction[StateC, StateC](function=lambda s: s)
        bad_seq = Sequence[StateA, StateB](steps=[bad_step])
        good_else = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=bad_seq,
            else_branch=good_else,
        )
        with pytest.raises(TypeMismatchError):
            validate_construct(cond)

    def test_recurses_into_else_branch(self):
        """Errors inside else_branch are caught."""
        good_then = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        bad_step = FunctionAction[StateC, StateC](function=lambda s: s)
        bad_seq = Sequence[StateA, StateB](steps=[bad_step])
        cond = Conditional[StateA, StateB](
            condition=lambda s: True,
            then_branch=good_then,
            else_branch=bad_seq,
        )
        with pytest.raises(TypeMismatchError):
            validate_construct(cond)

    def test_recurses_into_no_else_then_branch(self):
        """Errors inside then_branch are caught (no else, detour pattern)."""
        bad_step = FunctionAction[StateC, StateC](function=lambda s: s)
        bad_seq = Sequence[StateA, StateA](steps=[bad_step])
        cond = Conditional[StateA, StateA](
            condition=lambda s: True,
            then_branch=bad_seq,
        )
        with pytest.raises(TypeMismatchError):
            validate_construct(cond)


# ======================================================================
# GateAction Validation
# ======================================================================


class TestGateActionValidation:
    def test_valid_prompt_key(self):
        gate = GateAction[GateState, GateOutput](
            interaction="human_stdin",
            prompt_key="escalation_context",
        )
        validate_construct(gate)  # should not raise

    def test_invalid_prompt_key(self):
        gate = GateAction[GateState, GateOutput](
            interaction="human_stdin",
            prompt_key="nonexistent_field",
        )
        with pytest.raises(InvalidPromptKeyError) as exc_info:
            validate_construct(gate)
        assert exc_info.value.prompt_key == "nonexistent_field"
        assert "should_block" in exc_info.value.available_fields
        assert "escalation_context" in exc_info.value.available_fields


# ======================================================================
# Process.validate() and Public API
# ======================================================================


class TestProcessValidate:
    def test_valid_plan_passes(self):
        from agent_foundry.constructs.process import Process

        s1 = FunctionAction[StateA, StateB](function=lambda s: StateB.model_construct())
        s2 = FunctionAction[StateB, StateC](function=lambda s: StateC.model_construct())
        seq = Sequence[StateA, StateC](steps=[s1, s2])
        process = Process(root=seq)
        process.validate()  # should not raise

    def test_invalid_plan_raises(self):
        from agent_foundry.constructs.process import Process

        bad = FunctionAction[StateC, StateC](function=lambda s: s)
        seq = Sequence[StateA, StateB](steps=[bad])
        process = Process(root=seq)
        with pytest.raises(TypeMismatchError):
            process.validate()


class TestValidatorPublicAPI:
    def test_import_validate_construct_from_package(self):
        from agent_foundry.constructs import validate_construct

        assert validate_construct is not None

    def test_import_errors_from_package(self):
        from agent_foundry.constructs import (
            ConstructValidationError,
            InvalidPromptKeyError,
            TypeMismatchError,
        )

        assert ConstructValidationError is not None
        assert TypeMismatchError is not None
        assert InvalidPromptKeyError is not None


# ======================================================================
# AgentAction composition validation
# ======================================================================


class _AgentValInput(BaseModel):
    value: str


class _AgentValOutput(BaseModel):
    value: str
    result: str


def _stub_prompt_builder_for_validator(state):
    return "prompt"


def _stub_instructions_for_validator(_state: object) -> str:
    return "# instructions"


def _stub_executor_for_validator(*, construct, prompt) -> _AgentValOutput:
    return _AgentValOutput(value="v", result="r")


def _make_agent_action(input_type, output_type):
    """Build an AgentAction with all required fields populated."""
    return AgentAction[input_type, output_type](
        name="test-agent",
        model="claude-sonnet-4-6",
        prompt_builder=_stub_prompt_builder_for_validator,
        instructions_provider=_stub_instructions_for_validator,
        executor=_stub_executor_for_validator,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    )


class TestAgentActionCompositionValidation:
    """AgentAction composes correctly inside parent constructs."""

    def test_standalone_agent_action_validates(self):
        action = _make_agent_action(_AgentValInput, _AgentValOutput)
        validate_construct(action)  # should not raise

    def test_agent_action_in_sequence_validates_types(self):
        action = _make_agent_action(_AgentValInput, _AgentValOutput)
        seq = Sequence[_AgentValInput, _AgentValOutput](steps=[action])
        validate_construct(seq)  # should not raise

    def test_agent_action_in_sequence_with_missing_input_raises(self):
        class _OtherInput(BaseModel):
            other: str

        action = _make_agent_action(_OtherInput, _AgentValOutput)
        seq = Sequence[_AgentValInput, _AgentValOutput](steps=[action])
        with pytest.raises(TypeMismatchError):
            validate_construct(seq)


# ======================================================================
# AICall validation
# ======================================================================


class _AIReqInput(BaseModel):
    text: str


class _AIReqOutput(BaseModel):
    result: str


class TestAICallValidation:
    def test_standalone_ai_call_validates(self):
        from agent_foundry.ai_models.inference import InferenceParameters
        from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
        from agent_foundry.constructs.ai_call import AICall, ModelInput

        entry = ModelEntry(
            model_id="fake",
            provider=object(),
            capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
        )
        action = AICall[_AIReqInput, _AIReqOutput](
            model_input=ModelInput[_AIReqInput](
                instructions="do the thing",
                prompt=lambda s: s.text,
            ),
            parameters=InferenceParameters(max_tokens=256),
            model=entry,
        )
        validate_construct(action)  # must not raise

    def test_ai_call_in_sequence_validates(self):
        from agent_foundry.ai_models.inference import InferenceParameters
        from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
        from agent_foundry.constructs.ai_call import AICall, ModelInput
        from agent_foundry.constructs.models import Sequence

        entry = ModelEntry(
            model_id="fake",
            provider=object(),
            capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
        )
        action = AICall[_AIReqInput, _AIReqOutput](
            model_input=ModelInput[_AIReqInput](
                instructions="do the thing",
                prompt=lambda s: s.text,
            ),
            parameters=InferenceParameters(max_tokens=256),
            model=entry,
        )
        seq = Sequence[_AIReqInput, _AIReqOutput](steps=[action])
        validate_construct(seq)  # must not raise


class TestAsyncFunctionActionValidation:
    """AsyncFunctionAction is registered with a validator (no unknown-type)."""

    def test_validates_without_raising(self):
        from agent_foundry.constructs.models import AsyncFunctionAction

        async def fn(state: StateA) -> StateA:
            return state

        action = AsyncFunctionAction[StateA, StateA](function=fn)
        validate_construct(action)  # must not raise
