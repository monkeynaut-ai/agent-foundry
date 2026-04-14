"""Tests for primitive compiler."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.compiler.primitive_compiler import compile_primitive, run_primitive_plan
from agent_foundry.primitives.errors import PrimitiveCompilationError
from agent_foundry.primitives.models import (
    Conditional,
    FunctionAction,
    GateAction,
    Loop,
    Retry,
    Sequence,
)
from agent_foundry.primitives.plan import PrimitivePlan

# -- Test fixtures --


class InputState(BaseModel):
    query: str


class OutputState(BaseModel):
    query: str
    result: str


class CounterState(BaseModel):
    value: int
    count: int


# ======================================================================
# Error Types
# ======================================================================


class TestPrimitiveCompilationError:
    def test_is_exception(self):
        err = PrimitiveCompilationError("compilation failed", primitive_type="FunctionAction")
        assert isinstance(err, Exception)
        assert str(err) == "compilation failed"
        assert err.primitive_type == "FunctionAction"


# ======================================================================
# State Type Derivation
# ======================================================================


class TestDeriveStateType:
    def test_single_model(self):
        from agent_foundry.compiler.primitive_compiler import _derive_state_type

        state_type = _derive_state_type(CounterState, CounterState)
        hints = state_type.__annotations__
        assert "value" in hints
        assert "count" in hints

    def test_unions_input_and_output_fields(self):
        from agent_foundry.compiler.primitive_compiler import _derive_state_type

        state_type = _derive_state_type(InputState, OutputState)
        hints = state_type.__annotations__
        assert "query" in hints
        assert "result" in hints

    def test_annotations_are_any(self):
        from agent_foundry.compiler.primitive_compiler import _derive_state_type

        state_type = _derive_state_type(InputState, OutputState)
        hints = state_type.__annotations__
        for v in hints.values():
            assert v is Any


# ======================================================================
# Compiler Registry
# ======================================================================


class TestCompilerRegistry:
    def test_register_and_retrieve(self):
        from agent_foundry.compiler.primitive_compiler import _compiler_registry
        from agent_foundry.primitives.models import FunctionAction

        # FunctionAction should be registered by module load
        assert FunctionAction in _compiler_registry

    def test_unknown_type_raises(self):
        from pydantic import BaseModel

        from agent_foundry.compiler.primitive_compiler import compile_primitive
        from agent_foundry.primitives.models import Primitive
        from agent_foundry.primitives.plan import PrimitivePlan
        from agent_foundry.primitives.validators import register_validator

        # A custom Primitive subclass with a registered validator (no-op) but
        # no compiler registered — exercises the compiler's unknown-type path.
        class _UncompiledPrim[I: BaseModel, O: BaseModel](Primitive[I, O]):
            pass

        register_validator(_UncompiledPrim, lambda p: None)

        prim = _UncompiledPrim[InputState, InputState]()
        plan = PrimitivePlan(root=prim)
        with pytest.raises(PrimitiveCompilationError, match="No compiler registered"):
            compile_primitive(plan)

    def test_duplicate_registration_raises(self):
        """Re-registering a compiler for the same type is a footgun; raise instead of clobbering."""
        from agent_foundry.compiler.primitive_compiler import register_compiler
        from agent_foundry.primitives.models import Primitive

        class _DuplicateCompilerPrim[I: BaseModel, O: BaseModel](Primitive[I, O]):
            pass

        def _first(graph, prim, prefix, gate_ids):
            return ("", "")

        def _second(graph, prim, prefix, gate_ids):
            return ("", "")

        register_compiler(_DuplicateCompilerPrim, _first)
        with pytest.raises(ValueError, match="_DuplicateCompilerPrim"):
            register_compiler(_DuplicateCompilerPrim, _second)


# ======================================================================
# Boundary Validation
# ======================================================================


class TestValidateBoundary:
    def test_valid_state(self):
        from agent_foundry.compiler.primitive_compiler import _validate_boundary

        result = _validate_boundary({"query": "hello"}, InputState, "test_node")
        assert result == {"query": "hello"}

    def test_extra_keys_preserved(self):
        """Extra keys pass through — LangGraph state may contain keys from other primitives."""
        from agent_foundry.compiler.primitive_compiler import _validate_boundary

        state = {"query": "hello", "other": "stuff"}
        result = _validate_boundary(state, InputState, "test_node")
        assert result["query"] == "hello"

    def test_missing_required_field_raises(self):
        from agent_foundry.compiler.primitive_compiler import _validate_boundary

        with pytest.raises(PrimitiveCompilationError):
            _validate_boundary({}, InputState, "test_node")


# ======================================================================
# State Scoping
# ======================================================================


class TestScopeIn:
    def test_extracts_only_model_fields(self):
        from agent_foundry.compiler.primitive_compiler import _scope_in

        parent_state = {"query": "hello", "result": "world", "extra": "ignored"}
        scoped = _scope_in(parent_state, InputState)
        assert scoped == {"query": "hello"}
        assert "result" not in scoped
        assert "extra" not in scoped

    def test_validates_required_fields(self):
        from agent_foundry.compiler.primitive_compiler import _scope_in

        with pytest.raises(PrimitiveCompilationError):
            _scope_in({}, InputState)


class TestScopeOut:
    def test_extracts_only_output_fields(self):
        from agent_foundry.compiler.primitive_compiler import _scope_out

        child_result = {"query": "hello", "result": "HELLO", "internal": "temp"}
        scoped = _scope_out(child_result, OutputState)
        assert scoped == {"query": "hello", "result": "HELLO"}
        assert "internal" not in scoped

    def test_validates_output(self):
        from agent_foundry.compiler.primitive_compiler import _scope_out

        with pytest.raises(PrimitiveCompilationError):
            _scope_out({}, OutputState)  # missing required fields


# ======================================================================
# FunctionAction Compilation
# ======================================================================


class TransformOutput(BaseModel):
    result: str


class TestCompileFunctionAction:
    def test_validates_input_boundary(self):
        action = FunctionAction[InputState, TransformOutput](
            function=lambda s: TransformOutput(result=s.query.upper()),
        )
        plan = PrimitivePlan(root=action)
        graph = compile_primitive(plan)
        with pytest.raises(PrimitiveCompilationError):
            graph.invoke({})  # missing required 'query'

    def test_run_primitive_plan_typed(self):
        """run_primitive_plan accepts and returns Pydantic models."""
        action = FunctionAction[InputState, TransformOutput](
            function=lambda s: TransformOutput(result=s.query.upper()),
        )
        plan = PrimitivePlan(root=action)
        result = run_primitive_plan(plan, InputState(query="hello"))
        assert isinstance(result, TransformOutput)
        assert result.result == "HELLO"

    def test_run_primitive_plan_default_input(self):
        class DefaultInput(BaseModel):
            value: str = "default"

        class DefaultOutput(BaseModel):
            value: str
            result: str

        action = FunctionAction[DefaultInput, DefaultOutput](
            function=lambda s: DefaultOutput(value=s.value, result=s.value.upper()),
        )
        plan = PrimitivePlan(root=action)
        result = run_primitive_plan(plan)
        assert isinstance(result, DefaultOutput)
        assert result.result == "DEFAULT"

    def test_zero_arg_function(self):
        """Functions that take no arguments work without Empty input model."""
        from datetime import date

        class DateOut(BaseModel):
            today: date

        class Empty(BaseModel):
            pass

        def get_today() -> DateOut:
            return DateOut(today=date(2026, 4, 6))

        action = FunctionAction[Empty, DateOut](function=get_today)
        plan = PrimitivePlan(root=action)
        result = run_primitive_plan(plan)
        assert isinstance(result, DateOut)
        assert result.today == date(2026, 4, 6)


# ======================================================================
# Sequence Compilation
# ======================================================================


class MidState(BaseModel):
    query: str
    mid: str


class TestCompileSequence:
    def test_two_steps_chain(self):
        step1 = FunctionAction[InputState, MidState](
            function=lambda s: MidState(query=s.query, mid=s.query.upper()),
        )
        step2 = FunctionAction[MidState, OutputState](
            function=lambda s: OutputState(query=s.mid, result=f"processed:{s.mid}"),
        )
        seq = Sequence[InputState, OutputState](steps=[step1, step2])
        plan = PrimitivePlan(root=seq)
        result = run_primitive_plan(plan, InputState(query="hello"))
        assert result.result == "processed:HELLO"

    def test_three_steps_order(self):
        """Verify steps execute in order by accumulating into a list."""

        class ListState(BaseModel):
            items: list[str] = []

        def append_a(s: ListState) -> ListState:
            return ListState(items=[*s.items, "a"])

        def append_b(s: ListState) -> ListState:
            return ListState(items=[*s.items, "b"])

        def append_c(s: ListState) -> ListState:
            return ListState(items=[*s.items, "c"])

        s1 = FunctionAction[ListState, ListState](function=append_a)
        s2 = FunctionAction[ListState, ListState](function=append_b)
        s3 = FunctionAction[ListState, ListState](function=append_c)
        seq = Sequence[ListState, ListState](steps=[s1, s2, s3])
        plan = PrimitivePlan(root=seq)
        result = run_primitive_plan(plan, ListState(items=[]))
        assert result.items == ["a", "b", "c"]

    def test_step_reads_from_accumulated_state(self):
        """Step 2 reads a field from Sequence input that step 1 didn't produce."""
        from datetime import date, timedelta

        class SeqIn(BaseModel):
            offset: int

        class DateState(BaseModel):
            today: date

        class ResultState(BaseModel):
            offset: int
            today: date

        class SeqOut(BaseModel):
            result: str

        def get_today(s: SeqIn) -> DateState:
            return DateState(today=date(2026, 4, 6))

        def add_days(s: ResultState) -> SeqOut:
            later = s.today + timedelta(days=s.offset)
            return SeqOut(result=str(later))

        step1 = FunctionAction[SeqIn, DateState](function=get_today)
        step2 = FunctionAction[ResultState, SeqOut](function=add_days)
        seq = Sequence[SeqIn, SeqOut](steps=[step1, step2])
        plan = PrimitivePlan(root=seq)
        result = run_primitive_plan(plan, SeqIn(offset=3))
        assert result.result == "2026-04-09"

    def test_output_from_intermediate_step(self):
        """Sequence output includes a field produced by an intermediate step, not the last."""

        class In(BaseModel):
            x: str

        class Mid(BaseModel):
            mid_value: str

        class Final(BaseModel):
            final_value: str

        class Out(BaseModel):
            mid_value: str
            final_value: str

        step1 = FunctionAction[In, Mid](
            function=lambda s: Mid(mid_value=s.x.upper()),
        )
        step2 = FunctionAction[Mid, Final](
            function=lambda s: Final(final_value=f"done:{s.mid_value}"),
        )
        seq = Sequence[In, Out](steps=[step1, step2])
        plan = PrimitivePlan(root=seq)
        result = run_primitive_plan(plan, In(x="hello"))
        assert result.mid_value == "HELLO"
        assert result.final_value == "done:HELLO"

    def test_three_steps_each_add_field(self):
        """Three steps, each adds a different field. Output assembles from all three."""

        class StepIn(BaseModel):
            seed: str

        class AOut(BaseModel):
            a: str

        class BIn(BaseModel):
            a: str

        class BOut(BaseModel):
            b: str

        class CIn(BaseModel):
            a: str
            b: str

        class COut(BaseModel):
            c: str

        class SeqOut(BaseModel):
            a: str
            b: str
            c: str

        step1 = FunctionAction[StepIn, AOut](
            function=lambda s: AOut(a=s.seed + "_a"),
        )
        step2 = FunctionAction[BIn, BOut](
            function=lambda s: BOut(b=s.a + "_b"),
        )
        step3 = FunctionAction[CIn, COut](
            function=lambda s: COut(c=s.a + "_" + s.b + "_c"),
        )
        seq = Sequence[StepIn, SeqOut](steps=[step1, step2, step3])
        plan = PrimitivePlan(root=seq)
        result = run_primitive_plan(plan, StepIn(seed="x"))
        assert result.a == "x_a"
        assert result.b == "x_a_b"
        assert result.c == "x_a_x_a_b_c"

    def test_validation_error_missing_field(self):
        """Step declares a required field not in accumulated state — fails at validation."""
        from agent_foundry.primitives.errors import TypeMismatchError

        class In(BaseModel):
            x: str

        class NeedsY(BaseModel):
            y: int  # not produced by any previous step

        class Out(BaseModel):
            result: str

        step1 = FunctionAction[In, In](function=lambda s: s)
        step2 = FunctionAction[NeedsY, Out](
            function=lambda s: Out(result=str(s.y)),
        )
        seq = Sequence[In, Out](steps=[step1, step2])
        plan = PrimitivePlan(root=seq)
        with pytest.raises(TypeMismatchError, match=r"requires fields.*y.*not available"):
            compile_primitive(plan)


# ======================================================================
# Conditional Compilation
# ======================================================================


class BranchState(BaseModel):
    value: str
    flag: bool


class TestCompileConditional:
    def test_then_branch_taken(self):
        then = FunctionAction[BranchState, BranchState](
            function=lambda s: BranchState(value="then", flag=s.flag),
        )
        else_ = FunctionAction[BranchState, BranchState](
            function=lambda s: BranchState(value="else", flag=s.flag),
        )
        cond = Conditional[BranchState, BranchState](
            condition=lambda s: s.flag,
            then_branch=then,
            else_branch=else_,
        )
        plan = PrimitivePlan(root=cond)
        result = run_primitive_plan(plan, BranchState(value="start", flag=True))
        assert result.value == "then"

    def test_else_branch_taken(self):
        then = FunctionAction[BranchState, BranchState](
            function=lambda s: BranchState(value="then", flag=s.flag),
        )
        else_ = FunctionAction[BranchState, BranchState](
            function=lambda s: BranchState(value="else", flag=s.flag),
        )
        cond = Conditional[BranchState, BranchState](
            condition=lambda s: s.flag,
            then_branch=then,
            else_branch=else_,
        )
        plan = PrimitivePlan(root=cond)
        result = run_primitive_plan(plan, BranchState(value="start", flag=False))
        assert result.value == "else"

    def test_no_else_passthrough(self):
        then = FunctionAction[BranchState, BranchState](
            function=lambda s: BranchState(value="detoured", flag=s.flag),
        )
        cond = Conditional[BranchState, BranchState](
            condition=lambda s: s.flag,
            then_branch=then,
        )
        plan = PrimitivePlan(root=cond)
        result = run_primitive_plan(plan, BranchState(value="original", flag=False))
        assert result.value == "original"

    def test_no_else_condition_true(self):
        then = FunctionAction[BranchState, BranchState](
            function=lambda s: BranchState(value="detoured", flag=s.flag),
        )
        cond = Conditional[BranchState, BranchState](
            condition=lambda s: s.flag,
            then_branch=then,
        )
        plan = PrimitivePlan(root=cond)
        result = run_primitive_plan(plan, BranchState(value="original", flag=True))
        assert result.value == "detoured"


# ======================================================================
# Loop Compilation
# ======================================================================


class LoopInput(BaseModel):
    items: list[str]
    processed: list[str] = []
    current_item: str = ""


class TestCompileLoop:
    def test_iterates_over_collection(self):
        body = FunctionAction[LoopInput, LoopInput](
            function=lambda s: LoopInput(
                items=s.items,
                processed=[*s.processed, s.current_item.upper()],
                current_item=s.current_item,
            ),
        )
        loop = Loop[LoopInput, LoopInput](
            over=lambda s: s.items,
            item_key="current_item",
            body=body,
        )
        plan = PrimitivePlan(root=loop)
        result = run_primitive_plan(plan, LoopInput(items=["a", "b", "c"], processed=[]))
        assert result.processed == ["A", "B", "C"]

    def test_respects_max_iterations(self):
        body = FunctionAction[LoopInput, LoopInput](
            function=lambda s: LoopInput(
                items=s.items,
                processed=[*s.processed, s.current_item],
                current_item=s.current_item,
            ),
        )
        loop = Loop[LoopInput, LoopInput](
            over=lambda s: s.items,
            item_key="current_item",
            body=body,
            max_iterations=2,
        )
        plan = PrimitivePlan(root=loop)
        result = run_primitive_plan(plan, LoopInput(items=["a", "b", "c", "d", "e"], processed=[]))
        assert len(result.processed) == 2

    def test_empty_collection(self):
        body = FunctionAction[LoopInput, LoopInput](
            function=lambda s: LoopInput(
                items=s.items,
                processed=[*s.processed, s.current_item],
                current_item=s.current_item,
            ),
        )
        loop = Loop[LoopInput, LoopInput](
            over=lambda s: s.items,
            item_key="current_item",
            body=body,
        )
        plan = PrimitivePlan(root=loop)
        result = run_primitive_plan(plan, LoopInput(items=[], processed=[]))
        assert result.processed == []

    def test_single_item(self):
        body = FunctionAction[LoopInput, LoopInput](
            function=lambda s: LoopInput(
                items=s.items,
                processed=[*s.processed, s.current_item.upper()],
                current_item=s.current_item,
            ),
        )
        loop = Loop[LoopInput, LoopInput](
            over=lambda s: s.items,
            item_key="current_item",
            body=body,
        )
        plan = PrimitivePlan(root=loop)
        result = run_primitive_plan(plan, LoopInput(items=["x"], processed=[]))
        assert result.processed == ["X"]


# ======================================================================
# Retry Compilation
# ======================================================================


class RetryState(BaseModel):
    attempts: int = 0
    done: bool = False


class TestCompileRetry:
    def test_succeeds_first_attempt(self):
        body = FunctionAction[RetryState, RetryState](
            function=lambda s: RetryState(attempts=s.attempts + 1, done=True),
        )
        retry = Retry[RetryState, RetryState](
            max_attempts=3,
            until=lambda s: s.done,
            body=body,
        )
        plan = PrimitivePlan(root=retry)
        result = run_primitive_plan(plan, RetryState(attempts=0, done=False))
        assert result.attempts == 1
        assert result.done is True

    def test_succeeds_second_attempt(self):
        call_count = {"n": 0}

        def body_fn(s: RetryState) -> RetryState:
            call_count["n"] += 1
            return RetryState(attempts=s.attempts + 1, done=call_count["n"] >= 2)

        body = FunctionAction[RetryState, RetryState](function=body_fn)
        retry = Retry[RetryState, RetryState](
            max_attempts=5,
            until=lambda s: s.done,
            body=body,
        )
        plan = PrimitivePlan(root=retry)
        result = run_primitive_plan(plan, RetryState(attempts=0, done=False))
        assert result.attempts == 2
        assert result.done is True

    def test_exhausted_exits_normally(self):
        """When max_attempts exhausted, Retry exits with domain state intact."""
        body = FunctionAction[RetryState, RetryState](
            function=lambda s: RetryState(attempts=s.attempts + 1, done=False),
        )
        retry = Retry[RetryState, RetryState](
            max_attempts=2,
            until=lambda s: s.done,
            body=body,
        )
        plan = PrimitivePlan(root=retry)
        result = run_primitive_plan(plan, RetryState(attempts=0, done=False))
        assert result.attempts == 2
        assert result.done is False

    def test_max_attempts_one(self):
        body = FunctionAction[RetryState, RetryState](
            function=lambda s: RetryState(attempts=s.attempts + 1, done=False),
        )
        retry = Retry[RetryState, RetryState](
            max_attempts=1,
            until=lambda s: s.done,
            body=body,
        )
        plan = PrimitivePlan(root=retry)
        result = run_primitive_plan(plan, RetryState(attempts=0, done=False))
        assert result.attempts == 1
        assert result.done is False


# ======================================================================
# GateAction Compilation
# ======================================================================


class GateInput(BaseModel):
    escalation_context: str
    value: str = ""


class GateOutput(BaseModel):
    escalation_context: str
    value: str
    human_response: str = ""


class TestCompileGateAction:
    def test_auto_injects_checkpointer(self):
        """Compile should succeed with a GateAction — MemorySaver auto-injected."""
        gate = GateAction[GateInput, GateOutput](
            interaction="human_stdin",
            prompt_key="escalation_context",
        )
        plan = PrimitivePlan(root=gate)
        graph = compile_primitive(plan)
        assert graph is not None

    def test_interrupts_execution(self):
        gate = GateAction[GateInput, GateOutput](
            interaction="human_stdin",
            prompt_key="escalation_context",
        )
        plan = PrimitivePlan(root=gate)
        graph = compile_primitive(plan)
        result = graph.invoke(
            {"escalation_context": "need help", "value": "stuck"},
            config={"configurable": {"thread_id": "test-1"}},
        )
        assert result["escalation_context"] == "need help"

    def test_prompt_key_value_in_interrupted_state(self):
        gate = GateAction[GateInput, GateOutput](
            interaction="human_stdin",
            prompt_key="escalation_context",
        )
        plan = PrimitivePlan(root=gate)
        graph = compile_primitive(plan)
        result = graph.invoke(
            {"escalation_context": "review failed twice", "value": "blocked"},
            config={"configurable": {"thread_id": "test-2"}},
        )
        assert result["escalation_context"] == "review failed twice"


# ======================================================================
# Nested Composition
# ======================================================================


class TestNestedComposition:
    def test_sequence_of_actions(self):
        class S(BaseModel):
            n: int = 0

        s1 = FunctionAction[S, S](function=lambda s: S(n=s.n + 1))
        s2 = FunctionAction[S, S](function=lambda s: S(n=s.n + 10))
        s3 = FunctionAction[S, S](function=lambda s: S(n=s.n + 100))
        seq = Sequence[S, S](steps=[s1, s2, s3])
        plan = PrimitivePlan(root=seq)
        result = run_primitive_plan(plan, S(n=0))
        assert result.n == 111

    def test_loop_body_is_sequence(self):
        class S(BaseModel):
            items: list[str] = []
            processed: list[str] = []
            current_item: str = ""

        step1 = FunctionAction[S, S](
            function=lambda s: S(
                items=s.items,
                processed=s.processed,
                current_item=s.current_item.upper(),
            ),
        )
        step2 = FunctionAction[S, S](
            function=lambda s: S(
                items=s.items,
                processed=[*s.processed, s.current_item],
                current_item=s.current_item,
            ),
        )
        body = Sequence[S, S](steps=[step1, step2])
        loop = Loop[S, S](over=lambda s: s.items, item_key="current_item", body=body)
        plan = PrimitivePlan(root=loop)
        result = run_primitive_plan(plan, S(items=["a", "b"], processed=[]))
        assert result.processed == ["A", "B"]

    def test_retry_then_conditional_escalation(self):
        """Retry exhausts, parent Conditional routes to escalation based on domain state."""

        class S(BaseModel):
            n: int = 0
            done: bool = False

        body = FunctionAction[S, S](
            function=lambda s: S(n=s.n + 1, done=False),
        )
        retry = Retry[S, S](max_attempts=2, until=lambda s: s.done, body=body)
        escalation = FunctionAction[S, S](
            function=lambda s: S(n=s.n, done=True),
        )
        check_exhausted = Conditional[S, S](
            condition=lambda s: not s.done,
            then_branch=escalation,
        )
        seq = Sequence[S, S](steps=[retry, check_exhausted])
        plan = PrimitivePlan(root=seq)
        result = run_primitive_plan(plan, S(n=0, done=False))
        assert result.n == 2
        assert result.done is True

    def test_sequence_containing_conditional(self):
        class S(BaseModel):
            value: str = ""
            flag: bool = True

        step1 = FunctionAction[S, S](function=lambda s: S(value="step1", flag=s.flag))
        then = FunctionAction[S, S](function=lambda s: S(value=s.value + "_then", flag=s.flag))
        else_ = FunctionAction[S, S](function=lambda s: S(value=s.value + "_else", flag=s.flag))
        cond = Conditional[S, S](
            condition=lambda s: s.flag,
            then_branch=then,
            else_branch=else_,
        )
        step3 = FunctionAction[S, S](function=lambda s: S(value=s.value + "_done", flag=s.flag))
        seq = Sequence[S, S](steps=[step1, cond, step3])
        plan = PrimitivePlan(root=seq)
        result = run_primitive_plan(plan, S(value="", flag=True))
        assert result.value == "step1_then_done"


# ======================================================================
# State Isolation
# ======================================================================


class TestStateIsolation:
    """Verify state scoping at every composition boundary."""

    def test_conditional_branches_dont_leak(self):
        """Branch internal fields don't appear in parent output."""

        class CondState(BaseModel):
            flag: bool
            value: str

        class BranchMid(BaseModel):
            flag: bool
            value: str
            branch_temp: str

        # then_branch is a Sequence with an internal field
        mid_step = FunctionAction[CondState, BranchMid](
            function=lambda s: BranchMid(flag=s.flag, value="then", branch_temp="should_not_leak"),
        )
        final_step = FunctionAction[BranchMid, CondState](
            function=lambda s: CondState(flag=s.flag, value=s.value),
        )
        then = Sequence[CondState, CondState](steps=[mid_step, final_step])
        else_ = FunctionAction[CondState, CondState](
            function=lambda s: CondState(flag=s.flag, value="else"),
        )
        cond = Conditional[CondState, CondState](
            condition=lambda s: s.flag,
            then_branch=then,
            else_branch=else_,
        )
        plan = PrimitivePlan(root=cond)
        result = run_primitive_plan(plan, CondState(flag=True, value="start"))
        assert result.value == "then"
        assert "branch_temp" not in result.model_dump()

    def test_retry_body_internals_dont_leak(self):
        """Retry body's internal fields don't appear in retry output."""

        class RS(BaseModel):
            attempts: int = 0
            done: bool = False

        class BodyMid(BaseModel):
            attempts: int
            done: bool
            debug_info: str = ""

        # Body is a Sequence with an internal field
        mid = FunctionAction[RS, BodyMid](
            function=lambda s: BodyMid(attempts=s.attempts + 1, done=True, debug_info="internal"),
        )
        final = FunctionAction[BodyMid, RS](
            function=lambda s: RS(attempts=s.attempts, done=s.done),
        )
        body = Sequence[RS, RS](steps=[mid, final])
        retry = Retry[RS, RS](
            max_attempts=3,
            until=lambda s: s.done,
            body=body,
        )
        plan = PrimitivePlan(root=retry)
        result = run_primitive_plan(plan, RS(attempts=0, done=False))
        assert result.attempts == 1
        assert "debug_info" not in result.model_dump()

    def test_sibling_primitives_dont_interfere(self):
        """Two sequential steps using the same internal field name don't collide."""

        class StepIn(BaseModel):
            value: str

        class StepMid(BaseModel):
            value: str
            temp: str

        class StepOut(BaseModel):
            value: str

        step1 = FunctionAction[StepIn, StepMid](
            function=lambda s: StepMid(value=s.value + "_a", temp="from_step1"),
        )
        step2 = FunctionAction[StepMid, StepOut](
            function=lambda s: StepOut(value=s.value + "_b"),
        )
        seq = Sequence[StepIn, StepOut](steps=[step1, step2])
        plan = PrimitivePlan(root=seq)
        result = run_primitive_plan(plan, StepIn(value="start"))
        assert result.value == "start_a_b"
        assert "temp" not in result.model_dump()

    def test_nested_loop_in_sequence_isolation(self):
        """Loop body internals don't leak to sequence siblings."""

        class SeqState(BaseModel):
            items: list[str]
            results: list[str] = []
            current_item: str = ""

        class BodyState(BaseModel):
            items: list[str]
            results: list[str]
            current_item: str
            processing_temp: str = ""

        pre = FunctionAction[SeqState, SeqState](
            function=lambda s: SeqState(
                items=s.items,
                results=["pre"],
                current_item=s.current_item,
            ),
        )
        body = FunctionAction[BodyState, BodyState](
            function=lambda s: BodyState(
                items=s.items,
                results=[*s.results, s.current_item.upper()],
                current_item=s.current_item,
                processing_temp="should_not_leak",
            ),
        )
        loop = Loop[SeqState, SeqState](
            over=lambda s: s.items,
            item_key="current_item",
            body=body,
        )
        post = FunctionAction[SeqState, SeqState](
            function=lambda s: SeqState(
                items=s.items,
                results=[*s.results, "post"],
                current_item=s.current_item,
            ),
        )
        seq = Sequence[SeqState, SeqState](steps=[pre, loop, post])
        plan = PrimitivePlan(root=seq)
        result = run_primitive_plan(plan, SeqState(items=["a", "b"], results=[]))
        assert result.results == ["pre", "A", "B", "post"]
        assert "processing_temp" not in result.model_dump()

    def test_loop_iterations_get_fresh_scope(self):
        """Each loop iteration starts fresh — body's internal fields reset to defaults."""

        class LoopIO(BaseModel):
            items: list[str]
            results: list[str] = []
            current_item: str = ""

        class BodyMid(BaseModel):
            items: list[str]
            results: list[str]
            current_item: str
            temp: str = ""

        def mid_fn(s: LoopIO) -> BodyMid:
            return BodyMid(
                items=s.items,
                results=s.results,
                current_item=s.current_item,
                temp="was_set",
            )

        def final_fn(s: BodyMid) -> LoopIO:
            assert s.temp == "was_set"
            return LoopIO(
                items=s.items,
                results=[*s.results, s.current_item],
                current_item=s.current_item,
            )

        mid = FunctionAction[LoopIO, BodyMid](function=mid_fn)
        final = FunctionAction[BodyMid, LoopIO](function=final_fn)
        body = Sequence[LoopIO, LoopIO](steps=[mid, final])
        loop = Loop[LoopIO, LoopIO](
            over=lambda s: s.items,
            item_key="current_item",
            body=body,
        )
        plan = PrimitivePlan(root=loop)
        result = run_primitive_plan(plan, LoopIO(items=["a", "b", "c"], results=[]))
        assert result.results == ["a", "b", "c"]
        assert "temp" not in result.model_dump()

    def test_three_levels_deep_isolation(self):
        """Isolation holds across Sequence > Loop > Sequence > FunctionAction."""

        class Outer(BaseModel):
            items: list[str]
            final: list[str] = []
            current_item: str = ""

        class Inner(BaseModel):
            items: list[str]
            final: list[str]
            current_item: str
            inner_temp: str = ""

        step1 = FunctionAction[Inner, Inner](
            function=lambda s: Inner(
                items=s.items,
                final=s.final,
                current_item=s.current_item,
                inner_temp="deep_internal",
            ),
        )
        step2 = FunctionAction[Inner, Outer](
            function=lambda s: Outer(
                items=s.items,
                final=[*s.final, s.current_item.upper()],
                current_item=s.current_item,
            ),
        )
        inner_seq = Sequence[Inner, Outer](steps=[step1, step2])
        loop = Loop[Outer, Outer](
            over=lambda s: s.items,
            item_key="current_item",
            body=inner_seq,
        )
        outer_seq = Sequence[Outer, Outer](steps=[loop])
        plan = PrimitivePlan(root=outer_seq)
        result = run_primitive_plan(plan, Outer(items=["x", "y"], final=[]))
        assert result.final == ["X", "Y"]
        assert "inner_temp" not in result.model_dump()
