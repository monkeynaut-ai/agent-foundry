"""Tests for typed state schema support in the compiler.

PR 1: state_schema on GraphWiringPlan + _build_state_type + typed StateGraph.
"""

from typing import Any

from agent_foundry.compiler.compiler import _build_state_type, compile_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan


def _stub_handler(
    state: dict[str, Any], node_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {**state, "result": "done"}


HANDLER_REGISTRY = {"test_role": _stub_handler}


def _simple_state_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "input_data": {"type": "object"},
            "result": {"type": ["string", "null"]},
        },
        "required": ["input_data"],
        "additionalProperties": False,
    }


def _plan_with_schema(state_schema: dict[str, Any] | None = None) -> GraphWiringPlan:
    return GraphWiringPlan(
        goal="test",
        nodes=[{"id": "n1", "role": "test_role", "config": {}}],
        edges=[],
        entry_point="n1",
        state_schema=state_schema,
    )


class TestBuildStateType:
    """_build_state_type converts JSON Schema into a TypedDict."""

    def test_given_schema_with_properties_when_built_then_typeddict_has_matching_keys(self):
        schema = _simple_state_schema()
        state_type = _build_state_type(schema)
        assert "input_data" in state_type.__annotations__
        assert "result" in state_type.__annotations__

    def test_given_schema_with_no_properties_when_built_then_typeddict_is_empty(self):
        schema = {"type": "object", "properties": {}}
        state_type = _build_state_type(schema)
        assert state_type.__annotations__ == {}

    def test_given_built_type_when_used_with_stategraph_then_creates_channels(self):
        from langgraph.graph import StateGraph

        schema = _simple_state_schema()
        state_type = _build_state_type(schema)
        graph = StateGraph(state_type)
        assert "input_data" in graph.channels
        assert "result" in graph.channels


class TestCompilePlanWithStateSchema:
    """compile_plan uses typed StateGraph when state_schema is present."""

    def test_given_plan_without_state_schema_when_compiled_then_succeeds(self, registry):
        plan = _plan_with_schema(state_schema=None)
        graph = compile_plan(plan, registry, handler_registry=HANDLER_REGISTRY)
        assert graph is not None

    def test_given_plan_with_state_schema_when_compiled_and_invoked_then_declared_keys_flow(
        self, registry
    ):
        plan = _plan_with_schema(state_schema=_simple_state_schema())
        graph = compile_plan(plan, registry, handler_registry=HANDLER_REGISTRY)
        result = graph.invoke({"input_data": {"key": "value"}})
        assert result["input_data"] == {"key": "value"}
        assert result["result"] == "done"

    def test_given_plan_with_state_schema_when_node_writes_declared_key_then_succeeds(
        self, registry
    ):
        plan = _plan_with_schema(state_schema=_simple_state_schema())
        graph = compile_plan(plan, registry, handler_registry=HANDLER_REGISTRY)
        result = graph.invoke({"input_data": {}})
        assert "result" in result
