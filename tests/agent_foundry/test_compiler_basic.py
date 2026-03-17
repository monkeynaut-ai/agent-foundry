"""S5.1 — Compile + run a trivial graph with one node.

Tests: compile returns runnable; invocation produces expected state mutation.
Feature flag: FF_COMPILER (default off until S5.2).
"""

from typing import Any

from agent_foundry.compiler.compiler import compile_plan, run_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan


def _one_node_plan() -> GraphWiringPlan:
    return GraphWiringPlan(
        goal="test",
        nodes=[{"id": "n1", "role": "schema_validator", "config": {}}],
        edges=[],
        entry_point="n1",
        role_versions={"schema_validator": "1.0.0"},
    )


def _two_node_plan() -> GraphWiringPlan:
    return GraphWiringPlan(
        goal="test",
        nodes=[
            {"id": "n1", "role": "rag_retriever", "config": {}},
            {"id": "n2", "role": "schema_validator", "config": {}},
        ],
        edges=[{"source": "n1", "target": "n2"}],
        entry_point="n1",
        role_versions={
            "rag_retriever": "1.0.0",
            "schema_validator": "1.0.0",
        },
    )


# Node handler registry for tests
def _stub_schema_validator(state: dict[str, Any]) -> dict[str, Any]:
    return {**state, "validated": True}


def _stub_rag_retriever(state: dict[str, Any]) -> dict[str, Any]:
    return {**state, "retrieved": True}


HANDLER_REGISTRY: dict[str, Any] = {
    "schema_validator": _stub_schema_validator,
    "rag_retriever": _stub_rag_retriever,
}


class TestCompileAndRun:
    """Compile a plan into a runnable LangGraph and execute it."""

    def test_compile_returns_runnable(self, registry):
        plan = _one_node_plan()
        graph = compile_plan(plan, registry, handler_registry=HANDLER_REGISTRY)
        assert graph is not None
        assert hasattr(graph, "invoke")

    def test_single_node_execution(self, registry):
        plan = _one_node_plan()
        graph = compile_plan(plan, registry, handler_registry=HANDLER_REGISTRY)
        result = graph.invoke({"input": "test"})
        assert result.get("validated") is True

    def test_two_node_execution(self, registry):
        plan = _two_node_plan()
        graph = compile_plan(plan, registry, handler_registry=HANDLER_REGISTRY)
        result = graph.invoke({"input": "test"})
        assert result.get("retrieved") is True
        assert result.get("validated") is True

    def test_state_mutation_flows_through_nodes(self, registry):
        plan = _two_node_plan()
        graph = compile_plan(plan, registry, handler_registry=HANDLER_REGISTRY)
        result = graph.invoke({"input": "hello"})
        assert result["input"] == "hello"


class TestRunPlan:
    """run_plan compiles and executes in one step."""

    def test_given_two_node_plan_when_run_plan_called_then_returns_final_state(self, registry):
        plan = _two_node_plan()
        result = run_plan(
            plan, registry, handler_registry=HANDLER_REGISTRY, initial_state={"input": "test"}
        )
        assert result.get("retrieved") is True
        assert result.get("validated") is True

    def test_given_run_plan_when_no_initial_state_then_uses_empty_dict(self, registry):
        plan = _one_node_plan()
        result = run_plan(plan, registry, handler_registry=HANDLER_REGISTRY)
        assert result.get("validated") is True
