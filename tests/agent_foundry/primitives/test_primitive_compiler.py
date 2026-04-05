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
        from agent_foundry.compiler.primitive_compiler import compile_primitive
        from agent_foundry.primitives.models import Primitive
        from agent_foundry.primitives.plan import PrimitivePlan

        prim = Primitive[InputState, InputState]()
        plan = PrimitivePlan(root=prim)
        with pytest.raises(PrimitiveCompilationError, match="No compiler registered"):
            compile_primitive(plan)


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
    def test_returns_compiled_graph(self):
        action = FunctionAction[InputState, TransformOutput](
            function=lambda s: TransformOutput(result=s.query.upper()),
        )
        plan = PrimitivePlan(root=action)
        graph = compile_primitive(plan)
        assert hasattr(graph, "invoke")

    def test_invoke_produces_correct_output(self):
        action = FunctionAction[InputState, TransformOutput](
            function=lambda s: TransformOutput(result=s.query.upper()),
        )
        plan = PrimitivePlan(root=action)
        graph = compile_primitive(plan)
        result = graph.invoke({"query": "hello"})
        assert result["result"] == "HELLO"

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


# ======================================================================
# Sequence Compilation
# ======================================================================


class MidState(BaseModel):
    query: str
    mid: str


class TestCompileSequence:
    def test_single_step(self):
        step = FunctionAction[InputState, TransformOutput](
            function=lambda s: TransformOutput(result=s.query.upper()),
        )
        seq = Sequence[InputState, TransformOutput](steps=[step])
        plan = PrimitivePlan(root=seq)
        graph = compile_primitive(plan)
        result = graph.invoke({"query": "hello"})
        assert result["result"] == "HELLO"

    def test_two_steps_chain(self):
        step1 = FunctionAction[InputState, MidState](
            function=lambda s: MidState(query=s.query, mid=s.query.upper()),
        )
        step2 = FunctionAction[MidState, OutputState](
            function=lambda s: OutputState(query=s.mid, result=f"processed:{s.mid}"),
        )
        seq = Sequence[InputState, OutputState](steps=[step1, step2])
        plan = PrimitivePlan(root=seq)
        graph = compile_primitive(plan)
        result = graph.invoke({"query": "hello"})
        assert result["result"] == "processed:HELLO"

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
        graph = compile_primitive(plan)
        result = graph.invoke({"items": []})
        assert result["items"] == ["a", "b", "c"]


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
        graph = compile_primitive(plan)
        result = graph.invoke({"value": "start", "flag": True})
        assert result["value"] == "then"

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
        graph = compile_primitive(plan)
        result = graph.invoke({"value": "start", "flag": False})
        assert result["value"] == "else"

    def test_no_else_passthrough(self):
        then = FunctionAction[BranchState, BranchState](
            function=lambda s: BranchState(value="detoured", flag=s.flag),
        )
        cond = Conditional[BranchState, BranchState](
            condition=lambda s: s.flag,
            then_branch=then,
        )
        plan = PrimitivePlan(root=cond)
        graph = compile_primitive(plan)
        result = graph.invoke({"value": "original", "flag": False})
        assert result["value"] == "original"

    def test_no_else_condition_true(self):
        then = FunctionAction[BranchState, BranchState](
            function=lambda s: BranchState(value="detoured", flag=s.flag),
        )
        cond = Conditional[BranchState, BranchState](
            condition=lambda s: s.flag,
            then_branch=then,
        )
        plan = PrimitivePlan(root=cond)
        graph = compile_primitive(plan)
        result = graph.invoke({"value": "original", "flag": True})
        assert result["value"] == "detoured"
