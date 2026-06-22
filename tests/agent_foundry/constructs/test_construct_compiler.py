"""Tests for construct compiler."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.compiler.compiler import compile_process, get_type_args
from agent_foundry.constructs.errors import ConstructCompilationError
from agent_foundry.constructs.models import (
    Conditional,
    FunctionAction,
    GateAction,
    Loop,
    Retry,
    Sequence,
)
from agent_foundry.constructs.process import Process
from agent_foundry.constructs.retry_types import RetryAborted


async def compile_and_run(process: Process, state: BaseModel | None = None) -> Any:
    """Minimal async test runner: compile and ainvoke without the full production pipeline."""
    _, root_out = get_type_args(process.root)
    graph = compile_process(process)
    input_dict = state.model_dump() if state is not None else {}
    result_dict = await graph.ainvoke(input_dict)
    return root_out.model_validate(result_dict)


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


class TestConstructCompilationError:
    def test_is_exception(self):
        err = ConstructCompilationError("compilation failed", construct_type="FunctionAction")
        assert isinstance(err, Exception)
        assert str(err) == "compilation failed"
        assert err.construct_type == "FunctionAction"


# ======================================================================
# State Type Derivation
# ======================================================================


class TestDeriveStateType:
    def test_single_model(self):
        from agent_foundry.compiler.compiler import _derive_state_type

        state_type = _derive_state_type(CounterState, CounterState)
        hints = state_type.__annotations__
        assert "value" in hints
        assert "count" in hints

    def test_unions_input_and_output_fields(self):
        from agent_foundry.compiler.compiler import _derive_state_type

        state_type = _derive_state_type(InputState, OutputState)
        hints = state_type.__annotations__
        assert "query" in hints
        assert "result" in hints

    def test_annotations_are_any(self):
        from agent_foundry.compiler.compiler import _derive_state_type

        state_type = _derive_state_type(InputState, OutputState)
        hints = state_type.__annotations__
        for v in hints.values():
            assert v is Any


# ======================================================================
# Compiler Registry
# ======================================================================


class TestCompilerRegistry:
    def test_register_and_retrieve(self):
        from agent_foundry.compiler.compiler import _compiler_registry
        from agent_foundry.constructs.models import FunctionAction

        # FunctionAction should be registered by module load
        assert FunctionAction in _compiler_registry

    def test_unknown_type_raises(self):
        from pydantic import BaseModel

        from agent_foundry.compiler.compiler import compile_process
        from agent_foundry.constructs.models import Construct
        from agent_foundry.constructs.process import Process
        from agent_foundry.constructs.validators import register_validator

        # A custom Construct subclass with a registered validator (no-op) but
        # no compiler registered — exercises the compiler's unknown-type path.
        class _UncompiledPrim[I: BaseModel, O: BaseModel](Construct[I, O]):
            def child_specs(self) -> list[tuple[Construct, str]]:
                return []

        register_validator(_UncompiledPrim, lambda p: None)

        prim = _UncompiledPrim[InputState, InputState]()
        process = Process(root=prim)
        with pytest.raises(ConstructCompilationError, match="No compiler registered"):
            compile_process(process)

    def test_duplicate_registration_raises(self):
        """Re-registering a compiler for the same type is a footgun; raise instead of clobbering."""
        from agent_foundry.compiler.compiler import register_compiler
        from agent_foundry.constructs.models import Construct

        class _DuplicateCompilerPrim[I: BaseModel, O: BaseModel](Construct[I, O]):
            def child_specs(self) -> list[tuple[Construct, str]]:
                return []

        def _first(graph, prim, prefix, gate_ids):
            return ("", "")

        def _second(graph, prim, prefix, gate_ids):
            return ("", "")

        register_compiler(_DuplicateCompilerPrim, _first)
        with pytest.raises(ValueError, match="_DuplicateCompilerPrim"):
            register_compiler(_DuplicateCompilerPrim, _second)


# ======================================================================
# State Scoping
# ======================================================================


class TestScopeIn:
    def test_extracts_only_model_fields(self):
        from agent_foundry.compiler.compiler import _scope_in

        parent_state = {"query": "hello", "result": "world", "extra": "ignored"}
        scoped = _scope_in(parent_state, InputState)
        assert scoped == {"query": "hello"}
        assert "result" not in scoped
        assert "extra" not in scoped

    def test_validates_required_fields(self):
        from agent_foundry.compiler.compiler import _scope_in

        with pytest.raises(ConstructCompilationError):
            _scope_in({}, InputState)


class TestScopeOut:
    def test_extracts_only_output_fields(self):
        from agent_foundry.compiler.compiler import _scope_out

        child_result = {"query": "hello", "result": "HELLO", "internal": "temp"}
        scoped = _scope_out(child_result, OutputState)
        assert scoped == {"query": "hello", "result": "HELLO"}
        assert "internal" not in scoped

    def test_validates_output(self):
        from agent_foundry.compiler.compiler import _scope_out

        with pytest.raises(ConstructCompilationError):
            _scope_out({}, OutputState)  # missing required fields


class TestValidateScopedInput:
    """`_validate_scoped_input` is the project-then-validate helper used
    inside per-construct compile functions to obtain a typed input model
    from accumulated state. Equivalent to `_scope_in` + a single
    `model_validate` call, returning the model instance instead of the
    filtered dict — callers want the model, not the dict."""

    def test_given_state_with_extras_when_scoped_then_returns_validated_model(self):
        from agent_foundry.compiler.compiler import _validate_scoped_input

        state = {"query": "hello", "extra": "ignored"}
        model = _validate_scoped_input(state, InputState, "test_node")
        assert isinstance(model, InputState)
        assert model.query == "hello"

    def test_given_state_missing_required_field_when_scoped_then_raises(self):
        from agent_foundry.compiler.compiler import _validate_scoped_input

        with pytest.raises(ConstructCompilationError) as excinfo:
            _validate_scoped_input({}, InputState, "test_node")
        # The node_id appears in the error so a developer can locate the
        # offending step in a multi-construct process.
        assert "test_node" in str(excinfo.value)

    def test_given_state_missing_optional_field_when_scoped_then_default_applied(self):
        from agent_foundry.compiler.compiler import _validate_scoped_input

        class WithOptional(BaseModel):
            required: str
            optional: int = 42

        model = _validate_scoped_input({"required": "hi"}, WithOptional, "test_node")
        assert model.required == "hi"
        assert model.optional == 42

    def test_given_input_type_without_extra_ignore_when_scoped_then_extras_dropped(self):
        """Pin the scope-then-validate ordering: even if the input model
        defaults to forbidding extras (via ConfigDict), projection drops
        them before validation so the call still succeeds."""
        from pydantic import ConfigDict

        from agent_foundry.compiler.compiler import _validate_scoped_input

        class StrictInput(BaseModel):
            model_config = ConfigDict(extra="forbid")
            query: str

        state = {"query": "hello", "extra": "ignored"}
        model = _validate_scoped_input(state, StrictInput, "test_node")
        assert model.query == "hello"


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
        process = Process(root=action)
        graph = compile_process(process)
        with pytest.raises(ConstructCompilationError):
            graph.invoke({})  # missing required 'query'

    @pytest.mark.asyncio
    async def test_input_with_extra_forbid_runs_when_accumulated_state_has_extras(self):
        """Pin scope-then-validate at the FunctionAction boundary inside
        a Sequence: even when a step's input model forbids extras, the
        compiler projects accumulated state down to declared fields
        before validation, so an upstream step's output fields (which
        downstream input models don't declare) don't blow up.

        Setup: step 1 produces `extra_from_step1`. Step 2's StrictInput
        forbids extras and only declares `query`. Without scope-then-
        validate at step 2's boundary, validation fails."""
        from pydantic import ConfigDict

        class Step1Out(BaseModel):
            query: str
            extra_from_step1: str  # downstream's StrictInput must NOT see this

        class StrictInput(BaseModel):
            model_config = ConfigDict(extra="forbid")
            query: str

        step1 = FunctionAction[InputState, Step1Out](
            function=lambda s: Step1Out(query=s.query, extra_from_step1="leak"),
        )
        step2 = FunctionAction[StrictInput, TransformOutput](
            function=lambda s: TransformOutput(result=s.query.upper()),
        )
        seq = Sequence[InputState, TransformOutput](steps=[step1, step2])
        process = Process(root=seq)
        result = await compile_and_run(process, InputState(query="hello"))
        assert result.result == "HELLO"

    @pytest.mark.asyncio
    async def test_compile_and_run_typed(self):
        """compile_and_run accepts and returns Pydantic models."""
        action = FunctionAction[InputState, TransformOutput](
            function=lambda s: TransformOutput(result=s.query.upper()),
        )
        process = Process(root=action)
        result = await compile_and_run(process, InputState(query="hello"))
        assert isinstance(result, TransformOutput)
        assert result.result == "HELLO"

    @pytest.mark.asyncio
    async def test_compile_and_run_default_input(self):
        class DefaultInput(BaseModel):
            value: str = "default"

        class DefaultOutput(BaseModel):
            value: str
            result: str

        action = FunctionAction[DefaultInput, DefaultOutput](
            function=lambda s: DefaultOutput(value=s.value, result=s.value.upper()),
        )
        process = Process(root=action)
        result = await compile_and_run(process)
        assert isinstance(result, DefaultOutput)
        assert result.result == "DEFAULT"

    @pytest.mark.asyncio
    async def test_zero_arg_function(self):
        """Functions that take no arguments work without Empty input model."""
        from datetime import date

        class DateOut(BaseModel):
            today: date

        class Empty(BaseModel):
            pass

        def get_today() -> DateOut:
            return DateOut(today=date(2026, 4, 6))

        action = FunctionAction[Empty, DateOut](function=get_today)
        process = Process(root=action)
        result = await compile_and_run(process)
        assert isinstance(result, DateOut)
        assert result.today == date(2026, 4, 6)


# ======================================================================
# Sequence Compilation
# ======================================================================


class MidState(BaseModel):
    query: str
    mid: str


class TestCompileSequence:
    @pytest.mark.asyncio
    async def test_two_steps_chain(self):
        step1 = FunctionAction[InputState, MidState](
            function=lambda s: MidState(query=s.query, mid=s.query.upper()),
        )
        step2 = FunctionAction[MidState, OutputState](
            function=lambda s: OutputState(query=s.mid, result=f"processed:{s.mid}"),
        )
        seq = Sequence[InputState, OutputState](steps=[step1, step2])
        process = Process(root=seq)
        result = await compile_and_run(process, InputState(query="hello"))
        assert result.result == "processed:HELLO"

    @pytest.mark.asyncio
    async def test_three_steps_order(self):
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
        process = Process(root=seq)
        result = await compile_and_run(process, ListState(items=[]))
        assert result.items == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_step_reads_from_accumulated_state(self):
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
        process = Process(root=seq)
        result = await compile_and_run(process, SeqIn(offset=3))
        assert result.result == "2026-04-09"

    @pytest.mark.asyncio
    async def test_output_from_intermediate_step(self):
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
        process = Process(root=seq)
        result = await compile_and_run(process, In(x="hello"))
        assert result.mid_value == "HELLO"
        assert result.final_value == "done:HELLO"

    @pytest.mark.asyncio
    async def test_three_steps_each_add_field(self):
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
        process = Process(root=seq)
        result = await compile_and_run(process, StepIn(seed="x"))
        assert result.a == "x_a"
        assert result.b == "x_a_b"
        assert result.c == "x_a_x_a_b_c"

    def test_validation_error_missing_field(self):
        """Step declares a required field not in accumulated state — fails at validation."""
        from agent_foundry.constructs.errors import TypeMismatchError

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
        process = Process(root=seq)
        with pytest.raises(TypeMismatchError, match=r"requires fields.*y.*not available"):
            compile_process(process)


# ======================================================================
# Conditional Compilation
# ======================================================================


class BranchState(BaseModel):
    value: str
    flag: bool


class TestCompileConditional:
    @pytest.mark.asyncio
    async def test_then_branch_taken(self):
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
        process = Process(root=cond)
        result = await compile_and_run(process, BranchState(value="start", flag=True))
        assert result.value == "then"

    @pytest.mark.asyncio
    async def test_else_branch_taken(self):
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
        process = Process(root=cond)
        result = await compile_and_run(process, BranchState(value="start", flag=False))
        assert result.value == "else"

    @pytest.mark.asyncio
    async def test_no_else_passthrough(self):
        then = FunctionAction[BranchState, BranchState](
            function=lambda s: BranchState(value="detoured", flag=s.flag),
        )
        cond = Conditional[BranchState, BranchState](
            condition=lambda s: s.flag,
            then_branch=then,
        )
        process = Process(root=cond)
        result = await compile_and_run(process, BranchState(value="original", flag=False))
        assert result.value == "original"

    @pytest.mark.asyncio
    async def test_no_else_condition_true(self):
        then = FunctionAction[BranchState, BranchState](
            function=lambda s: BranchState(value="detoured", flag=s.flag),
        )
        cond = Conditional[BranchState, BranchState](
            condition=lambda s: s.flag,
            then_branch=then,
        )
        process = Process(root=cond)
        result = await compile_and_run(process, BranchState(value="original", flag=True))
        assert result.value == "detoured"

    @pytest.mark.asyncio
    async def test_cond_in_with_extra_forbid_runs_when_accumulated_state_has_extras(self):
        """Pin scope-then-validate at the Conditional's `condition`
        boundary: when an upstream step's output adds fields not in
        cond_in, those fields must be projected away before the
        condition function sees them, even if cond_in forbids extras.

        The branches' invocations are unchanged — they receive full
        accumulated state and project at their own boundaries."""
        from pydantic import ConfigDict

        class StrictBranchState(BaseModel):
            model_config = ConfigDict(extra="forbid")
            value: str
            flag: bool

        class SeqIn(BaseModel):
            value: str
            flag: bool

        class Step1Out(BaseModel):
            value: str
            flag: bool
            extra_from_step1: str  # cond_in must NOT see this

        step1 = FunctionAction[SeqIn, Step1Out](
            function=lambda s: Step1Out(value=s.value, flag=s.flag, extra_from_step1="leak"),
        )
        then_branch = FunctionAction[StrictBranchState, StrictBranchState](
            function=lambda s: StrictBranchState(value="then", flag=s.flag),
        )
        cond = Conditional[StrictBranchState, StrictBranchState](
            condition=lambda s: s.flag,
            then_branch=then_branch,
        )
        seq = Sequence[SeqIn, StrictBranchState](steps=[step1, cond])
        process = Process(root=seq)
        result = await compile_and_run(process, SeqIn(value="start", flag=True))
        assert result.value == "then"


# ======================================================================
# Loop Compilation
# ======================================================================


class LoopInput(BaseModel):
    items: list[str]
    processed: list[str] = []
    current_item: str = ""


class TestCompileLoop:
    @pytest.mark.asyncio
    async def test_iterates_over_collection(self):
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
        process = Process(root=loop)
        result = await compile_and_run(process, LoopInput(items=["a", "b", "c"], processed=[]))
        assert result.processed == ["A", "B", "C"]

    @pytest.mark.asyncio
    async def test_respects_max_iterations(self):
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
        process = Process(root=loop)
        result = await compile_and_run(
            process, LoopInput(items=["a", "b", "c", "d", "e"], processed=[])
        )
        assert len(result.processed) == 2

    @pytest.mark.asyncio
    async def test_empty_collection(self):
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
        process = Process(root=loop)
        result = await compile_and_run(process, LoopInput(items=[], processed=[]))
        assert result.processed == []

    @pytest.mark.asyncio
    async def test_single_item(self):
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
        process = Process(root=loop)
        result = await compile_and_run(process, LoopInput(items=["x"], processed=[]))
        assert result.processed == ["X"]

    @pytest.mark.asyncio
    async def test_loop_in_with_extra_forbid_runs_when_accumulated_state_has_extras(self):
        """Pin scope-then-validate at the Loop's `over` boundary: when an
        upstream step's output adds fields not in loop_in, those fields
        must be projected away before validation, even if loop_in
        forbids extras."""
        from pydantic import ConfigDict

        class StrictLoopIn(BaseModel):
            model_config = ConfigDict(extra="forbid")
            items: list[str]
            processed: list[str] = []
            current_item: str = ""

        class SeqIn(BaseModel):
            items: list[str]

        # Step1Out is a superset of StrictLoopIn's fields plus an extra
        # leak field. The Sequence validator pins that loop_in's fields
        # are reachable from accumulated state; the leak field is what
        # the runtime scope_in must drop before validation.
        class Step1Out(BaseModel):
            items: list[str]
            processed: list[str] = []
            current_item: str = ""
            extra_from_step1: str  # loop_in must NOT see this

        body = FunctionAction[StrictLoopIn, StrictLoopIn](
            function=lambda s: StrictLoopIn(
                items=s.items,
                processed=[*s.processed, s.current_item.upper()],
                current_item=s.current_item,
            ),
        )
        loop = Loop[StrictLoopIn, StrictLoopIn](
            over=lambda s: s.items,
            item_key="current_item",
            body=body,
        )
        step1 = FunctionAction[SeqIn, Step1Out](
            function=lambda s: Step1Out(items=s.items, extra_from_step1="leak"),
        )
        seq = Sequence[SeqIn, StrictLoopIn](steps=[step1, loop])
        process = Process(root=seq)
        result = await compile_and_run(process, SeqIn(items=["a", "b"]))
        assert result.processed == ["A", "B"]


# ======================================================================
# Retry Compilation
# ======================================================================


class RetryState(BaseModel):
    attempts: int = 0
    done: bool = False


class TestCompileRetry:
    @pytest.mark.asyncio
    async def test_succeeds_first_attempt(self):
        body = FunctionAction[RetryState, RetryState](
            function=lambda s: RetryState(attempts=s.attempts + 1, done=True),
        )
        retry = Retry[RetryState, RetryState](
            max_attempts=3,
            until=lambda s: s.done,
            body=body,
        )
        process = Process(root=retry)
        result = await compile_and_run(process, RetryState(attempts=0, done=False))
        assert result.attempts == 1
        assert result.done is True

    @pytest.mark.asyncio
    async def test_succeeds_second_attempt(self):
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
        process = Process(root=retry)
        result = await compile_and_run(process, RetryState(attempts=0, done=False))
        assert result.attempts == 2
        assert result.done is True

    @pytest.mark.asyncio
    async def test_exhausted_is_fail_closed(self):
        """When max_attempts exhausted without until() passing, Retry raises (interim fail-closed)."""
        body = FunctionAction[RetryState, RetryState](
            function=lambda s: RetryState(attempts=s.attempts + 1, done=False),
        )
        retry = Retry[RetryState, RetryState](
            max_attempts=2,
            until=lambda s: s.done,
            body=body,
        )
        process = Process(root=retry)
        with pytest.raises(RetryAborted):
            await compile_and_run(process, RetryState(attempts=0, done=False))

    @pytest.mark.asyncio
    async def test_max_attempts_one_exhaustion_is_fail_closed(self):
        body = FunctionAction[RetryState, RetryState](
            function=lambda s: RetryState(attempts=s.attempts + 1, done=False),
        )
        retry = Retry[RetryState, RetryState](
            max_attempts=1,
            until=lambda s: s.done,
            body=body,
        )
        process = Process(root=retry)
        with pytest.raises(RetryAborted):
            await compile_and_run(process, RetryState(attempts=0, done=False))

    @pytest.mark.asyncio
    async def test_retry_in_with_extra_forbid_runs_when_accumulated_state_has_extras(self):
        """Pin scope-then-validate at the Retry's `until` boundary: when
        an upstream step's output adds fields not in retry_in, those
        fields must be projected away before validation, even if
        retry_in forbids extras."""
        from pydantic import ConfigDict

        class StrictRetryState(BaseModel):
            model_config = ConfigDict(extra="forbid")
            attempts: int = 0
            done: bool = False

        class SeqIn(BaseModel):
            attempts: int = 0
            done: bool = False

        class Step1Out(BaseModel):
            attempts: int = 0
            done: bool = False
            extra_from_step1: str  # retry_in must NOT see this

        step1 = FunctionAction[SeqIn, Step1Out](
            function=lambda s: Step1Out(attempts=s.attempts, done=s.done, extra_from_step1="leak"),
        )
        body = FunctionAction[StrictRetryState, StrictRetryState](
            function=lambda s: StrictRetryState(attempts=s.attempts + 1, done=True),
        )
        retry = Retry[StrictRetryState, StrictRetryState](
            max_attempts=3, until=lambda s: s.done, body=body
        )
        seq = Sequence[SeqIn, StrictRetryState](steps=[step1, retry])
        process = Process(root=seq)
        result = await compile_and_run(process, SeqIn(attempts=0, done=False))
        assert result.attempts == 1
        assert result.done is True


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
        process = Process(root=gate)
        graph = compile_process(process)
        assert graph is not None

    def test_interrupts_execution(self):
        gate = GateAction[GateInput, GateOutput](
            interaction="human_stdin",
            prompt_key="escalation_context",
        )
        process = Process(root=gate)
        graph = compile_process(process)
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
        process = Process(root=gate)
        graph = compile_process(process)
        result = graph.invoke(
            {"escalation_context": "review failed twice", "value": "blocked"},
            config={"configurable": {"thread_id": "test-2"}},
        )
        assert result["escalation_context"] == "review failed twice"


# ======================================================================
# Nested Composition
# ======================================================================


class TestNestedComposition:
    @pytest.mark.asyncio
    async def test_sequence_of_actions(self):
        class S(BaseModel):
            n: int = 0

        s1 = FunctionAction[S, S](function=lambda s: S(n=s.n + 1))
        s2 = FunctionAction[S, S](function=lambda s: S(n=s.n + 10))
        s3 = FunctionAction[S, S](function=lambda s: S(n=s.n + 100))
        seq = Sequence[S, S](steps=[s1, s2, s3])
        process = Process(root=seq)
        result = await compile_and_run(process, S(n=0))
        assert result.n == 111

    @pytest.mark.asyncio
    async def test_loop_body_is_sequence(self):
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
        process = Process(root=loop)
        result = await compile_and_run(process, S(items=["a", "b"], processed=[]))
        assert result.processed == ["A", "B"]

    @pytest.mark.asyncio
    async def test_retry_exhaustion_in_sequence_is_fail_closed(self):
        """Retry exhaustion inside a Sequence raises (interim fail-closed) before downstream steps."""

        class S(BaseModel):
            n: int = 0
            done: bool = False

        body = FunctionAction[S, S](
            function=lambda s: S(n=s.n + 1, done=False),
        )
        retry = Retry[S, S](max_attempts=2, until=lambda s: s.done, body=body)
        downstream = FunctionAction[S, S](
            function=lambda s: S(n=s.n, done=True),
        )
        seq = Sequence[S, S](steps=[retry, downstream])
        process = Process(root=seq)
        with pytest.raises(RetryAborted):
            await compile_and_run(process, S(n=0, done=False))

    @pytest.mark.asyncio
    async def test_sequence_containing_conditional(self):
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
        process = Process(root=seq)
        result = await compile_and_run(process, S(value="", flag=True))
        assert result.value == "step1_then_done"


# ======================================================================
# State Isolation
# ======================================================================


class TestStateIsolation:
    """Verify state scoping at every composition boundary."""

    @pytest.mark.asyncio
    async def test_conditional_branches_dont_leak(self):
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
        process = Process(root=cond)
        result = await compile_and_run(process, CondState(flag=True, value="start"))
        assert result.value == "then"
        assert "branch_temp" not in result.model_dump()

    @pytest.mark.asyncio
    async def test_retry_body_internals_dont_leak(self):
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
        process = Process(root=retry)
        result = await compile_and_run(process, RS(attempts=0, done=False))
        assert result.attempts == 1
        assert "debug_info" not in result.model_dump()

    @pytest.mark.asyncio
    async def test_sibling_constructs_dont_interfere(self):
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
        process = Process(root=seq)
        result = await compile_and_run(process, StepIn(value="start"))
        assert result.value == "start_a_b"
        assert "temp" not in result.model_dump()

    @pytest.mark.asyncio
    async def test_nested_loop_in_sequence_isolation(self):
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
        process = Process(root=seq)
        result = await compile_and_run(process, SeqState(items=["a", "b"], results=[]))
        assert result.results == ["pre", "A", "B", "post"]
        assert "processing_temp" not in result.model_dump()

    @pytest.mark.asyncio
    async def test_loop_iterations_get_fresh_scope(self):
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
        process = Process(root=loop)
        result = await compile_and_run(process, LoopIO(items=["a", "b", "c"], results=[]))
        assert result.results == ["a", "b", "c"]
        assert "temp" not in result.model_dump()

    @pytest.mark.asyncio
    async def test_three_levels_deep_isolation(self):
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
        process = Process(root=outer_seq)
        result = await compile_and_run(process, Outer(items=["x", "y"], final=[]))
        assert result.final == ["X", "Y"]
        assert "inner_temp" not in result.model_dump()
