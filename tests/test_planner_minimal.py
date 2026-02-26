"""S4.1 — Minimal planner that emits a valid plan without retrieval.

Tests: planner output validates against model; all node types in registry.
Feature flag: FF_PLANNER (default off until S4.3).
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from agent_foundry.planner.planner import WiringPlanner
from agent_foundry.planner.validators import validate_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import CapabilityRegistry

CAPABILITIES_DIR = Path(__file__).parent.parent / "capabilities"


@pytest.fixture
def registry():
    return CapabilityRegistry.from_directory(CAPABILITIES_DIR)


@pytest.fixture
def planner(registry):
    return WiringPlanner(registry=registry)


class TestMinimalPlanner:
    """Planner produces valid plans from goals."""

    def test_planner_returns_wiring_plan(self, planner):
        plan = planner.plan("decision-support")
        assert isinstance(plan, GraphWiringPlan)

    def test_plan_validates_against_registry(self, planner, registry):
        plan = planner.plan("decision-support")
        validate_plan(plan, registry)  # Should not raise

    def test_plan_has_nodes(self, planner):
        plan = planner.plan("decision-support")
        assert len(plan.nodes) > 0

    def test_plan_has_edges(self, planner):
        plan = planner.plan("decision-support")
        assert len(plan.edges) > 0

    def test_plan_has_entry_point(self, planner):
        plan = planner.plan("decision-support")
        assert plan.entry_point != ""
        node_ids = {n.id for n in plan.nodes}
        assert plan.entry_point in node_ids

    def test_all_node_capabilities_in_registry(self, planner, registry):
        plan = planner.plan("decision-support")
        for node in plan.nodes:
            assert registry.get(node.capability) is not None, (
                f"Capability '{node.capability}' not in registry"
            )

    def test_plan_json_is_valid(self, planner):
        plan = planner.plan("decision-support")
        json_str = plan.model_dump_json()
        reconstructed = GraphWiringPlan.model_validate_json(json_str)
        assert reconstructed == plan
