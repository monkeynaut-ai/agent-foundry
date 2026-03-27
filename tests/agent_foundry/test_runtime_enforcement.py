"""Tests for runtime state schema enforcement.

PR 3: Handlers returning undeclared keys cause immediate failure.
"""

from typing import Any

import pytest

from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.compiler.errors import StateSchemaViolationError
from agent_foundry.planner.wiring_plan import GraphWiringPlan


def _good_handler(
    state: dict[str, Any], node_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"result": "done"}


def _bad_handler(
    state: dict[str, Any], node_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"result": "done", "undeclared_key": "oops"}


def _state_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "input_data": {"type": "object"},
            "result": {"type": ["string", "null"]},
        },
        "additionalProperties": False,
    }


def _plan(state_schema: dict[str, Any] | None = None) -> GraphWiringPlan:
    return GraphWiringPlan(
        goal="test",
        nodes=[{"id": "n1", "role": "test_role", "config": {}}],
        edges=[],
        entry_point="n1",
        state_schema=state_schema,
    )


class TestRuntimeEnforcement:
    """Handler return values are checked against state_schema at runtime."""

    def test_given_declared_key_when_handler_returns_then_succeeds(self, registry):
        graph = compile_plan(
            _plan(state_schema=_state_schema()),
            registry,
            handler_registry={"test_role": _good_handler},
        )
        result = graph.invoke({"input_data": {}})
        assert result["result"] == "done"

    def test_given_undeclared_key_when_handler_returns_then_raises(self, registry):
        graph = compile_plan(
            _plan(state_schema=_state_schema()),
            registry,
            handler_registry={"test_role": _bad_handler},
        )
        with pytest.raises(StateSchemaViolationError, match="undeclared_key"):
            graph.invoke({"input_data": {}})

    def test_given_no_state_schema_when_handler_returns_extra_key_then_succeeds(self, registry):
        graph = compile_plan(
            _plan(state_schema=None),
            registry,
            handler_registry={"test_role": _bad_handler},
        )
        result = graph.invoke({"input_data": {}})
        assert result["undeclared_key"] == "oops"

    def test_given_undeclared_key_when_raised_then_error_has_node_id(self, registry):
        graph = compile_plan(
            _plan(state_schema=_state_schema()),
            registry,
            handler_registry={"test_role": _bad_handler},
        )
        with pytest.raises(StateSchemaViolationError) as exc_info:
            graph.invoke({"input_data": {}})
        assert exc_info.value.node_id == "n1"
        assert "undeclared_key" in exc_info.value.undeclared_keys
