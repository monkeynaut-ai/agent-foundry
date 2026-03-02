"""S5.1 — Compile + run a trivial graph with one node.

Tests: compile returns runnable; invocation produces expected state mutation.
Feature flag: FF_COMPILER (default off until S5.2).
"""

from pathlib import Path
from typing import Any

import pytest

from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import CapabilityRegistry

CAPABILITIES_DIR = Path(__file__).parent.parent.parent / "capabilities"


@pytest.fixture
def registry():
    return CapabilityRegistry.from_directory(CAPABILITIES_DIR)


def _one_node_plan() -> GraphWiringPlan:
    return GraphWiringPlan(
        goal="test",
        nodes=[{"id": "n1", "capability": "schema_validator", "config": {}}],
        edges=[],
        entry_point="n1",
        capability_versions={"schema_validator": "1.0.0"},
    )


def _two_node_plan() -> GraphWiringPlan:
    return GraphWiringPlan(
        goal="test",
        nodes=[
            {"id": "n1", "capability": "rag_retriever", "config": {}},
            {"id": "n2", "capability": "schema_validator", "config": {}},
        ],
        edges=[{"source": "n1", "target": "n2"}],
        entry_point="n1",
        capability_versions={
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
