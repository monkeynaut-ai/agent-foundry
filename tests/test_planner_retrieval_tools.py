"""S4.2-S4.4, S4.6-S4.7 — Planner retrieval, tools, HITL, no-snippet, determinism.

S4.2: planner consumes retrieved snippets; still emits valid plan.
S4.3: tool-required goal leads to tool_calling node + tools list.
S4.4: irreversible tool under high risk inserts breakpoint.
S4.6: empty retrieval triggers minimal plan or typed error.
S4.7: deterministic config yields byte-identical JSON; planning timeout.
"""

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from langchain_core.documents import Document

from agent_foundry.planner.errors import (
    PlanningInsufficientContextError,
    PlanningTimeoutError,
)
from agent_foundry.planner.planner import WiringPlanner
from agent_foundry.planner.validators import validate_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import CapabilityRegistry

CAPABILITIES_DIR = Path(__file__).parent.parent / "capabilities"


@pytest.fixture
def registry():
    return CapabilityRegistry.from_directory(CAPABILITIES_DIR)


def _make_snippets():
    return [
        Document(
            page_content="Capability: rag_retriever\nDescription: RAG retrieval",
            metadata={"source": "registry:rag_retriever", "chunk_id": "abc123"},
        ),
        Document(
            page_content="Capability: tool_calling\nDescription: Tool execution",
            metadata={"source": "registry:tool_calling", "chunk_id": "def456"},
        ),
    ]


# --- S4.2: Retrieval Integration ---

class TestRetrievalIntegration:
    """Planner consumes snippets and still produces valid plans."""

    def test_with_snippets_produces_valid_plan(self, registry):
        planner = WiringPlanner(registry=registry, snippets=_make_snippets())
        plan = planner.plan("decision-support")
        validate_plan(plan, registry)

    def test_snippets_influence_plan(self, registry):
        snippets = _make_snippets()
        planner = WiringPlanner(registry=registry, snippets=snippets)
        plan = planner.plan("decision-support")
        capabilities = {n.capability for n in plan.nodes}
        assert "rag_retriever" in capabilities


# --- S4.3: Tool Selection ---

class TestToolSelection:
    """Tool-required goals include tool_calling and tools list."""

    def test_tool_goal_includes_tool_calling_node(self, registry):
        planner = WiringPlanner(registry=registry)
        plan = planner.plan("decision-support-with-tools")
        capabilities = {n.capability for n in plan.nodes}
        assert "tool_calling" in capabilities

    def test_tool_goal_has_non_empty_tools_list(self, registry):
        planner = WiringPlanner(registry=registry)
        plan = planner.plan("decision-support-with-tools")
        assert len(plan.tools) > 0

    def test_tool_names_are_unique(self, registry):
        planner = WiringPlanner(registry=registry)
        plan = planner.plan("decision-support-with-tools")
        names = [t.name for t in plan.tools]
        assert len(names) == len(set(names))


# --- S4.4: Risk-Aware HITL Placement ---

class TestHITLPlacement:
    """High-risk irreversible tools get human approval breakpoint."""

    def test_high_risk_plan_inserts_breakpoint(self, registry):
        planner = WiringPlanner(registry=registry)
        plan = planner.plan("decision-support-with-tools", risk="high")
        assert plan.breakpoints == ["tools"]

    def test_high_risk_plan_adds_human_approval_gate_and_version(self, registry):
        planner = WiringPlanner(registry=registry)
        plan = planner.plan("decision-support-with-tools", risk="high")
        capabilities = {n.capability for n in plan.nodes}
        assert "human_approval_gate" in capabilities
        assert plan.capability_versions.get("human_approval_gate") == "1.0.0"

    def test_low_risk_plan_no_breakpoint(self, registry):
        planner = WiringPlanner(registry=registry)
        plan = planner.plan("decision-support", risk="low")
        assert len(plan.breakpoints) == 0


# --- S4.6: No-Snippet Behavior ---

class TestNoSnippetBehavior:
    """Empty retrieval produces minimal plan or typed error."""

    def test_no_snippets_produces_minimal_plan(self, registry):
        planner = WiringPlanner(registry=registry, snippets=[])
        plan = planner.plan("decision-support")
        assert isinstance(plan, GraphWiringPlan)

    def test_no_snippets_with_strict_mode_raises_error(self, registry):
        planner = WiringPlanner(registry=registry, snippets=[], strict=True)
        with pytest.raises(PlanningInsufficientContextError):
            planner.plan("unknown-goal-requiring-context")

    def test_empty_registry_raises_value_error(self):
        planner = WiringPlanner(registry=CapabilityRegistry(specs={}), snippets=[])
        with pytest.raises(ValueError, match="No capabilities available"):
            planner.plan("unknown-goal")


# --- S4.7: Determinism + Budget ---

class TestDeterminism:
    """Same inputs produce byte-identical output."""

    def test_deterministic_output(self, registry):
        planner = WiringPlanner(registry=registry)
        plan1 = planner.plan("decision-support")
        plan2 = planner.plan("decision-support")
        assert plan1.model_dump_json() == plan2.model_dump_json()


class TestBudgetEnforcement:
    """Planning timeout is enforced."""

    def test_timeout_raises_error(self, registry):
        planner = WiringPlanner(registry=registry, timeout_seconds=0.001)
        # Normal planning is fast enough, so we mock a slow plan
        original_plan = planner.plan

        def slow_plan(*args, **kwargs):
            time.sleep(1)
            return original_plan(*args, **kwargs)

        planner._slow_plan = slow_plan
        with patch.object(planner, "_generate_plan", side_effect=lambda *a, **k: time.sleep(1)):
            with pytest.raises(PlanningTimeoutError):
                planner.plan("decision-support")
