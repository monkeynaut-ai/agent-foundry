"""DS1-DS9 — Decision Support Demo tests.

DS1: Runnable demo entrypoint with static plan.
DS2: Evidence retrieval node + evidence written to state.
DS3: Structured recommendation schema enforced.
DS4: Citation validator gate.
DS5: Uncertainty completeness validator gate.
DS6: Evidence-first contract validator.
DS7: Tool-calling node with stub calculator.
DS8: Planner produces the Decision Support demo plan.
DS9: Non-functional: end-to-end latency budgets.
"""

import json
import os
import time
from pathlib import Path

import pytest

from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.demo.runner import (
    DEMO_HANDLERS,
    RECOMMENDATION_SCHEMA,
    load_demo_plan,
    run_demo,
)
from agent_foundry.observability.gates import (
    citation_validator_gate,
    evidence_first_gate,
    schema_validator_gate,
    uncertainty_completeness_gate,
)
from agent_foundry.planner.planner import WiringPlanner
from agent_foundry.planner.validators import validate_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import CapabilityRegistry

CAPABILITIES_DIR = Path(__file__).parent.parent.parent / "capabilities"


@pytest.fixture
def registry():
    return CapabilityRegistry.from_directory(CAPABILITIES_DIR)


# --- DS1: Runnable Demo Entrypoint ---

class TestDS1Entrypoint:
    """Runner loads plan JSON and executes graph."""

    def test_load_static_plan(self):
        plan = load_demo_plan()
        assert isinstance(plan, GraphWiringPlan)
        assert plan.goal == "decision-support"

    def test_run_demo_produces_output(self, registry):
        result = run_demo("What should we do?", registry=registry)
        assert isinstance(result, dict)

    def test_run_demo_has_recommendation(self, registry):
        result = run_demo("What should we do?", registry=registry)
        assert "recommendation" in result


# --- DS2: Evidence Retrieval ---

class TestDS2EvidenceRetrieval:
    """Evidence retrieval populates state correctly."""

    def test_retrieved_evidence_exists(self, registry):
        result = run_demo("What is the best approach?", registry=registry)
        assert "retrieved_evidence" in result
        assert len(result["retrieved_evidence"]) >= 1

    def test_evidence_has_required_fields(self, registry):
        result = run_demo("What is the best approach?", registry=registry)
        for evidence in result["retrieved_evidence"]:
            assert "id" in evidence
            assert "text" in evidence
            assert evidence["id"] != ""
            assert evidence["text"] != ""


# --- DS3: Structured Recommendation Schema ---

class TestDS3StructuredRecommendation:
    """Recommendation output matches schema."""

    def test_recommendation_matches_schema(self, registry):
        result = run_demo("What should we prioritize?", registry=registry)
        rec = result["recommendation"]
        gate_result = schema_validator_gate(rec, RECOMMENDATION_SCHEMA)
        assert gate_result["valid"] is True

    def test_malformed_recommendation_fails_schema(self):
        bad_rec = {"text": "just a string"}
        gate_result = schema_validator_gate(bad_rec, RECOMMENDATION_SCHEMA)
        assert gate_result["valid"] is False


# --- DS4: Citation Validator ---

class TestDS4CitationValidator:
    """Citations reference valid evidence IDs."""

    def test_valid_citations_in_demo(self, registry):
        result = run_demo("What should we do?", registry=registry)
        assert result.get("citations_valid") is True
        assert "gate_failure" not in result

    def test_fabricated_citation_fails(self):
        result = citation_validator_gate(
            evidence_ids=["e1", "fabricated_id"],
            retrieved_evidence=[{"id": "e1"}, {"id": "e2"}],
        )
        assert result["valid"] is False
        assert "fabricated_id" in result["missing_ids"]


# --- DS5: Uncertainty Completeness ---

class TestDS5UncertaintyCompleteness:
    """Uncertainty fields are complete."""

    def test_demo_has_valid_uncertainty(self, registry):
        result = run_demo("What should we do?", registry=registry)
        assert result.get("uncertainty_valid") is True
        assert "gate_failure" not in result

    def test_missing_confidence_fails(self):
        result = uncertainty_completeness_gate({"rationale": "test"})
        assert result["valid"] is False


# --- DS6: Evidence-First Contract ---

class TestDS6EvidenceFirstContract:
    """Evidence-first policy is enforced."""

    def test_demo_passes_evidence_first(self, registry):
        result = run_demo("What should we do?", registry=registry)
        assert result.get("evidence_valid") is True
        assert result.get("outcome") == "recommendation_valid"
        assert "gate_failure" not in result

    def test_no_evidence_returns_insufficient(self):
        result = evidence_first_gate([], {"text": "do something"})
        assert result["valid"] is False
        assert result["outcome"] == "insufficient_evidence"

    def test_missing_assumptions_fails(self):
        result = evidence_first_gate(
            [{"id": "e1", "text": "evidence"}],
            {"text": "do something"},
        )
        assert result["valid"] is False


# --- DS7: Tool Calling ---

class TestDS7ToolCalling:
    """Tool calling with stub calculator."""

    def test_calculator_tool_produces_result(self, registry):
        # Load plan with tools
        plan = load_demo_plan()
        plan_data = plan.model_dump()
        # Add tool_calling node
        plan_data["nodes"].insert(1, {
            "id": "tools",
            "capability": "tool_calling",
            "config": {},
        })
        plan_data["edges"][0] = {"source": "retriever", "target": "tools"}
        plan_data["edges"].insert(1, {"source": "tools", "target": "output"})
        plan_data["tools"] = [{"name": "calculator", "args_schema": {"type": "object"}}]
        plan_data["capability_versions"]["tool_calling"] = "1.0.0"

        plan_with_tools = GraphWiringPlan(**plan_data)
        graph = compile_plan(plan_with_tools, registry, handler_registry=DEMO_HANDLERS)
        result = graph.invoke({"question": "Calculate 2+2", "domain": "math", "constraints": []})
        assert result.get("tool_result") is not None
        assert result["tool_result"]["result"] == 4


# --- DS8: Planner Produces Plan ---

class TestDS8PlannerProducesPlan:
    """Planner deterministically generates the Decision Support plan."""

    def test_planner_emits_valid_plan(self, registry):
        planner = WiringPlanner(registry=registry)
        plan = planner.plan("decision-support")
        validate_plan(plan, registry)

    def test_planner_includes_required_node_types(self, registry):
        planner = WiringPlanner(registry=registry)
        plan = planner.plan("decision-support")
        capabilities = {n.capability for n in plan.nodes}
        assert "rag_retriever" in capabilities
        assert "structured_output_pydantic" in capabilities
        assert "schema_validator" in capabilities

    def test_planner_output_is_deterministic(self, registry):
        planner = WiringPlanner(registry=registry)
        plan1 = planner.plan("decision-support")
        plan2 = planner.plan("decision-support")
        assert plan1.model_dump_json() == plan2.model_dump_json()


# --- DS9: End-to-End Performance (Benchmark) ---

@pytest.mark.benchmark
class TestDS9Performance:
    """End-to-end latency budget: p95 <= 2s."""

    def test_e2e_p95_under_2s(self, registry):
        import statistics

        slow_factor = float(os.getenv("AF_BENCHMARK_SLOW_FACTOR", "1.0"))
        p95_budget_ms = 2000 * slow_factor
        timings = []
        for _ in range(10):
            start = time.perf_counter()
            run_demo("What should we do?", registry=registry)
            elapsed_ms = (time.perf_counter() - start) * 1000
            timings.append(elapsed_ms)

        timings.sort()
        p95 = timings[int(len(timings) * 0.95)]
        median = statistics.median(timings)
        print(
            f"\nDemo E2E: median={median:.1f}ms, p95={p95:.1f}ms, "
            f"budget={p95_budget_ms:.1f}ms"
        )
        assert p95 <= p95_budget_ms, f"p95 {p95:.1f}ms exceeds {p95_budget_ms:.1f}ms budget"
