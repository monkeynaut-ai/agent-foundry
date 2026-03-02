"""Archipelago pipeline plan — parsing, validation, and planner integration tests."""

import json
from pathlib import Path

import pytest

from agent_foundry.planner.validators import validate_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import CapabilityRegistry

PLAN_PATH = Path(__file__).parent.parent.parent / "src" / "archipelago" / "pipeline_plan.json"
PRODUCT_CAPS_DIR = Path(__file__).parent.parent.parent / "src" / "archipelago" / "capabilities"


@pytest.fixture
def plan_data():
    return json.loads(PLAN_PATH.read_text())


@pytest.fixture
def plan(plan_data):
    return GraphWiringPlan(**plan_data)


@pytest.fixture
def registry():
    return CapabilityRegistry.with_product_specs(PRODUCT_CAPS_DIR)


# ── Commit 1: Parse tests ──


class TestParsePlan:
    def test_given_pipeline_json_when_parsed_then_goal_is_archipelago_pipeline(self, plan):
        assert plan.goal == "archipelago-pipeline"

    def test_given_pipeline_json_when_parsed_then_has_5_nodes(self, plan):
        assert len(plan.nodes) == 5

    def test_given_pipeline_json_when_parsed_then_has_4_edges(self, plan):
        assert len(plan.edges) == 4

    def test_given_pipeline_json_when_parsed_then_entry_point_is_strategy(self, plan):
        assert plan.entry_point == "strategy"

    def test_given_pipeline_json_when_parsed_then_breakpoints_contain_spec_approval_gate(
        self, plan
    ):
        assert "spec_approval_gate" in plan.breakpoints

    def test_given_pipeline_json_when_round_tripped_then_no_field_loss(self, plan_data):
        plan = GraphWiringPlan(**plan_data)
        dumped = json.loads(plan.model_dump_json())
        reconstructed = GraphWiringPlan(**dumped)
        assert reconstructed == plan

    def test_given_pipeline_json_when_capability_versions_inspected_then_all_nodes_covered(
        self, plan
    ):
        node_capabilities = {n.capability for n in plan.nodes}
        versioned_capabilities = set(plan.capability_versions.keys())
        assert node_capabilities == versioned_capabilities


# ── Commit 2: Validation tests ──


class TestValidatePlan:
    def test_given_pipeline_plan_and_full_registry_when_validated_then_no_errors(
        self, plan, registry
    ):
        validate_plan(plan, registry)

    def test_given_pipeline_plan_when_duplicate_check_runs_then_no_duplicate_ids(self, plan):
        node_ids = [n.id for n in plan.nodes]
        assert len(node_ids) == len(set(node_ids))

    def test_given_pipeline_plan_when_dangling_edge_check_runs_then_no_dangles(self, plan):
        node_ids = {n.id for n in plan.nodes}
        for edge in plan.edges:
            assert edge.source in node_ids, f"Dangling source: {edge.source}"
            assert edge.target in node_ids, f"Dangling target: {edge.target}"

    def test_given_pipeline_plan_when_breakpoint_check_runs_then_all_breakpoints_valid(self, plan):
        node_ids = {n.id for n in plan.nodes}
        for bp in plan.breakpoints:
            assert bp in node_ids, f"Breakpoint references non-existent node: {bp}"

    def test_given_pipeline_plan_when_version_coverage_check_runs_then_all_covered(self, plan):
        for node in plan.nodes:
            assert node.capability in plan.capability_versions, (
                f"Missing version for capability: {node.capability}"
            )
