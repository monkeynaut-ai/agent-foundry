"""Tests for primitive compiler."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.primitives.errors import PrimitiveCompilationError

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
