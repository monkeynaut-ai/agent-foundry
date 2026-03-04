"""Shared fixtures for agent_foundry tests."""

from pathlib import Path

import pytest

from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import CapabilityRegistry

CAPABILITIES_DIR = Path(__file__).parent.parent.parent / "capabilities"


@pytest.fixture
def registry():
    return CapabilityRegistry.from_directory(CAPABILITIES_DIR)


def make_plan(**overrides) -> GraphWiringPlan:
    """Shared factory for creating test wiring plans."""
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
