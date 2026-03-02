"""S3.3 — Referential integrity: unknown capabilities, dangling edges, duplicate node ids.

Tests: unknown capability -> UnknownCapabilityError;
       duplicate ids -> DuplicateNodeIdError;
       dangling edge -> DanglingEdgeError.
Feature flag: FF_PLAN_VALIDATION (default on).
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from agent_foundry.planner.errors import (
    DanglingEdgeError,
    DuplicateNodeIdError,
    UnknownCapabilityError,
)
from agent_foundry.planner.validators import validate_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import CapabilityRegistry

CAPABILITIES_DIR = Path(__file__).parent.parent.parent / "capabilities"


@pytest.fixture
def registry():
    return CapabilityRegistry.from_directory(CAPABILITIES_DIR)


def _make_plan(**overrides) -> GraphWiringPlan:
    defaults = {
        "goal": "test",
        "nodes": [
            {"id": "n1", "capability": "rag_retriever"},
            {"id": "n2", "capability": "schema_validator"},
        ],
        "edges": [{"source": "n1", "target": "n2"}],
        "entry_point": "n1",
        "capability_versions": {
            "rag_retriever": "1.0.0",
            "schema_validator": "1.0.0",
        },
    }
    defaults.update(overrides)
    return GraphWiringPlan(**defaults)


class TestUnknownCapability:
    """Nodes referencing capabilities not in registry are rejected."""

    def test_unknown_capability_raises_error(self, registry):
        plan = _make_plan(
            nodes=[
                {"id": "n1", "capability": "totally_fake_capability"},
            ],
            edges=[],
            entry_point="n1",
            capability_versions={"totally_fake_capability": "1.0.0"},
        )
        with pytest.raises(UnknownCapabilityError) as exc_info:
            validate_plan(plan, registry)
        assert "totally_fake_capability" in str(exc_info.value)

    def test_valid_capabilities_pass(self, registry):
        plan = _make_plan()
        validate_plan(plan, registry)  # Should not raise


class TestDuplicateNodeIds:
    """Duplicate node IDs are detected."""

    def test_duplicate_ids_raises_error(self, registry):
        plan = _make_plan(
            nodes=[
                {"id": "same_id", "capability": "rag_retriever"},
                {"id": "same_id", "capability": "schema_validator"},
            ],
            edges=[],
            entry_point="same_id",
            capability_versions={
                "rag_retriever": "1.0.0",
                "schema_validator": "1.0.0",
            },
        )
        with pytest.raises(DuplicateNodeIdError) as exc_info:
            validate_plan(plan, registry)
        assert "same_id" in str(exc_info.value)


class TestDanglingEdges:
    """Edges referencing non-existent nodes are detected."""

    def test_dangling_source_raises_error(self, registry):
        plan = _make_plan(edges=[{"source": "nonexistent", "target": "n2"}])
        with pytest.raises(DanglingEdgeError) as exc_info:
            validate_plan(plan, registry)
        assert "nonexistent" in str(exc_info.value)

    def test_dangling_target_raises_error(self, registry):
        plan = _make_plan(edges=[{"source": "n1", "target": "nonexistent"}])
        with pytest.raises(DanglingEdgeError) as exc_info:
            validate_plan(plan, registry)
        assert "nonexistent" in str(exc_info.value)


class TestFeatureFlag:
    """FF_PLAN_VALIDATION controls validation."""

    def test_flag_off_skips_validation(self, registry):
        plan = _make_plan(
            nodes=[
                {"id": "n1", "capability": "totally_fake"},
            ],
            edges=[],
            entry_point="n1",
            capability_versions={"totally_fake": "1.0.0"},
        )
        with patch("agent_foundry.planner.validators.FF_PLAN_VALIDATION", False):
            validate_plan(plan, registry)  # Should not raise
