"""S1.5 — Execute a capability node with input/output schema enforcement.

Tests: valid input returns output; invalid input -> typed error;
       invalid output -> validation report with field path.
Feature flag: FF_SCHEMA_ENFORCEMENT (default on).
"""

from typing import Any
from unittest.mock import patch

import pytest

from agent_foundry.registry.errors import CapabilityExecutionError
from agent_foundry.registry.execution import execute_capability
from agent_foundry.registry.spec import (
    CapabilitySpec,
    ImplementationPointer,
    QualityControls,
)


def _make_spec(
    inputs_schema: dict | None = None,
    outputs_schema: dict | None = None,
) -> CapabilitySpec:
    return CapabilitySpec(
        name="test_cap",
        description="A test capability",
        version="1.0.0",
        implementation=ImplementationPointer(
            module="builtins", class_name="dict"
        ),
        inputs_schema=inputs_schema or {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        outputs_schema=outputs_schema or {
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
        },
        tags=[],
        quality_controls=QualityControls(),
    )


def _echo_handler(inputs: dict[str, Any]) -> dict[str, Any]:
    """Simple handler that wraps input query into result."""
    return {"result": inputs.get("query", "")}


def _bad_output_handler(inputs: dict[str, Any]) -> dict[str, Any]:
    """Handler that returns output missing required fields."""
    return {"wrong_field": "oops"}


def _non_string_output_handler(inputs: dict[str, Any]) -> dict[str, Any]:
    """Handler that returns wrong type for result."""
    return {"result": 12345}


class TestValidExecution:
    """Valid inputs produce valid outputs."""

    def test_valid_input_returns_output(self):
        spec = _make_spec()
        result = execute_capability(spec, {"query": "hello"}, _echo_handler)
        assert result == {"result": "hello"}

    def test_output_matches_handler_return(self):
        spec = _make_spec()
        result = execute_capability(spec, {"query": "test"}, _echo_handler)
        assert result["result"] == "test"


class TestInputValidation:
    """Invalid inputs produce typed errors."""

    def test_missing_required_input_raises_error(self):
        spec = _make_spec()
        with pytest.raises(CapabilityExecutionError) as exc_info:
            execute_capability(spec, {}, _echo_handler)
        assert exc_info.value.phase == "input_validation"
        assert "query" in str(exc_info.value)

    def test_wrong_type_input_raises_error(self):
        spec = _make_spec()
        with pytest.raises(CapabilityExecutionError) as exc_info:
            execute_capability(spec, {"query": 12345}, _echo_handler)
        assert exc_info.value.phase == "input_validation"

    def test_input_error_includes_capability_name(self):
        spec = _make_spec()
        with pytest.raises(CapabilityExecutionError) as exc_info:
            execute_capability(spec, {}, _echo_handler)
        assert exc_info.value.capability_name == "test_cap"


class TestOutputValidation:
    """Invalid outputs produce validation reports with field paths."""

    def test_missing_required_output_raises_error(self):
        spec = _make_spec()
        with pytest.raises(CapabilityExecutionError) as exc_info:
            execute_capability(spec, {"query": "hello"}, _bad_output_handler)
        assert exc_info.value.phase == "output_validation"
        assert "result" in str(exc_info.value)

    def test_wrong_type_output_raises_error(self):
        spec = _make_spec()
        with pytest.raises(CapabilityExecutionError) as exc_info:
            execute_capability(spec, {"query": "hello"}, _non_string_output_handler)
        assert exc_info.value.phase == "output_validation"

    def test_output_error_includes_field_path(self):
        spec = _make_spec()
        with pytest.raises(CapabilityExecutionError) as exc_info:
            execute_capability(spec, {"query": "hello"}, _bad_output_handler)
        assert exc_info.value.field_paths is not None
        assert len(exc_info.value.field_paths) > 0


class TestFeatureFlag:
    """FF_SCHEMA_ENFORCEMENT controls validation."""

    def test_flag_off_skips_input_validation(self):
        spec = _make_spec()
        with patch("agent_foundry.registry.execution.FF_SCHEMA_ENFORCEMENT", False):
            result = execute_capability(spec, {}, _echo_handler)
        assert result == {"result": ""}

    def test_flag_off_skips_output_validation(self):
        spec = _make_spec()
        with patch("agent_foundry.registry.execution.FF_SCHEMA_ENFORCEMENT", False):
            result = execute_capability(spec, {"query": "hello"}, _bad_output_handler)
        assert result == {"wrong_field": "oops"}
