"""S6.6 — Compiler enforces gate execution on all paths to final.

Tests: plan missing gate on one path fails compilation.
"""

import pytest

from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.compiler.errors import PlanCompilationError
from agent_foundry.planner.wiring_plan import GraphWiringPlan

HANDLERS = {
    "rag_retriever": lambda s, c=None: {**s, "retrieved": True},
    "schema_validator": lambda s, c=None: {**s, "validated": True},
    "structured_output_pydantic": lambda s, c=None: {**s, "structured": True},
    "citation_validator": lambda s, c=None: {**s, "citations_checked": True},
}

EVAL_GATE_ROLES = {
    "schema_validator",
    "citation_validator",
    "uncertainty_completeness_validator",
    "evidence_first_contract",
}


class TestGateEnforcement:
    """All paths to final node must pass through at least one eval gate."""

    def test_plan_without_gate_fails(self, registry):
        plan = GraphWiringPlan(
            goal="test",
            nodes=[
                {"id": "n1", "role": "rag_retriever"},
                {"id": "n2", "role": "structured_output_pydantic"},
            ],
            edges=[{"source": "n1", "target": "n2"}],
            entry_point="n1",
            state_schema={"type": "object", "properties": {}, "additionalProperties": True},
            role_versions={
                "rag_retriever": "1.0.0",
                "structured_output_pydantic": "1.0.0",
            },
        )
        with pytest.raises(PlanCompilationError, match="eval gate"):
            compile_plan(plan, registry, handler_registry=HANDLERS, enforce_gates=True)


class TestGateEnforcementEdgeCases:
    """Edge cases for _check_eval_gates_on_paths."""

    def test_single_node_no_gate_raises_error(self, registry):
        plan = GraphWiringPlan(
            goal="test",
            nodes=[{"id": "n1", "role": "rag_retriever"}],
            edges=[],
            entry_point="n1",
            state_schema={"type": "object", "properties": {}, "additionalProperties": True},
            role_versions={"rag_retriever": "1.0.0"},
        )
        with pytest.raises(PlanCompilationError, match="eval gate"):
            compile_plan(plan, registry, handler_registry=HANDLERS, enforce_gates=True)

    def test_gate_is_terminal_node_passes(self, registry):
        plan = GraphWiringPlan(
            goal="test",
            nodes=[
                {"id": "n1", "role": "rag_retriever"},
                {"id": "gate", "role": "schema_validator"},
            ],
            edges=[{"source": "n1", "target": "gate"}],
            entry_point="n1",
            state_schema={"type": "object", "properties": {}, "additionalProperties": True},
            role_versions={
                "rag_retriever": "1.0.0",
                "schema_validator": "1.0.0",
            },
        )
        graph = compile_plan(plan, registry, handler_registry=HANDLERS, enforce_gates=True)
        assert graph is not None

    def test_plan_with_gate_passes(self, registry):
        plan = GraphWiringPlan(
            goal="test",
            nodes=[
                {"id": "n1", "role": "rag_retriever"},
                {"id": "gate", "role": "schema_validator"},
                {"id": "n2", "role": "structured_output_pydantic"},
            ],
            edges=[
                {"source": "n1", "target": "gate"},
                {"source": "gate", "target": "n2"},
            ],
            entry_point="n1",
            state_schema={"type": "object", "properties": {}, "additionalProperties": True},
            role_versions={
                "rag_retriever": "1.0.0",
                "schema_validator": "1.0.0",
                "structured_output_pydantic": "1.0.0",
            },
        )
        graph = compile_plan(plan, registry, handler_registry=HANDLERS, enforce_gates=True)
        result = graph.invoke({})
        assert result.get("validated") is True
        assert result.get("structured") is True

    def test_branching_plan_with_gate_bypass_fails(self, registry):
        plan = GraphWiringPlan(
            goal="test",
            nodes=[
                {"id": "start", "role": "rag_retriever"},
                {"id": "gate", "role": "schema_validator"},
                {"id": "final", "role": "structured_output_pydantic"},
            ],
            edges=[
                {"source": "start", "target": "gate", "condition": "needs_validation"},
                {"source": "start", "target": "final"},
                {"source": "gate", "target": "final"},
            ],
            entry_point="start",
            state_schema={"type": "object", "properties": {}, "additionalProperties": True},
            role_versions={
                "rag_retriever": "1.0.0",
                "schema_validator": "1.0.0",
                "structured_output_pydantic": "1.0.0",
            },
        )
        with pytest.raises(PlanCompilationError, match="eval gate"):
            compile_plan(plan, registry, handler_registry=HANDLERS, enforce_gates=True)
