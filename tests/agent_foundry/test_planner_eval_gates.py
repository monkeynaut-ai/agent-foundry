"""S4.5 — Eval gate inclusion + reachability.

Tests: plan contains eval_gates; graph reachability analysis says reachable.
Feature flag: FF_EVAL_GATES (default on).
"""

from pathlib import Path

import pytest

from agent_foundry.planner.planner import WiringPlanner
from agent_foundry.registry.registry import CapabilityRegistry

CAPABILITIES_DIR = Path(__file__).parent.parent.parent / "capabilities"

EVAL_GATE_CAPABILITIES = {
    "schema_validator", "citation_validator",
    "uncertainty_completeness_validator", "evidence_first_contract",
}


@pytest.fixture
def registry():
    return CapabilityRegistry.from_directory(CAPABILITIES_DIR)


class TestEvalGateInclusion:
    """Planner includes at least one eval gate."""

    def test_plan_contains_eval_gate(self, registry):
        planner = WiringPlanner(registry=registry)
        plan = planner.plan("decision-support")
        gate_nodes = [n for n in plan.nodes if n.capability in EVAL_GATE_CAPABILITIES]
        assert len(gate_nodes) >= 1

    def test_eval_gate_reachable_from_entry(self, registry):
        planner = WiringPlanner(registry=registry)
        plan = planner.plan("decision-support")

        # BFS from entry point
        adjacency = {}
        for edge in plan.edges:
            adjacency.setdefault(edge.source, []).append(edge.target)

        reachable = set()
        queue = [plan.entry_point]
        while queue:
            node = queue.pop(0)
            if node in reachable:
                continue
            reachable.add(node)
            queue.extend(adjacency.get(node, []))

        gate_nodes = {n.id for n in plan.nodes if n.capability in EVAL_GATE_CAPABILITIES}
        reachable_gates = gate_nodes & reachable
        assert len(reachable_gates) >= 1, "No eval gate reachable from entry point"
