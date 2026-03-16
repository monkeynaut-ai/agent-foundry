"""Shared fixtures for agent_foundry tests."""

from pathlib import Path

import pytest

from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import RoleRegistry

ROLES_DIR = Path(__file__).parent.parent.parent / "src" / "agent_foundry" / "roles"


@pytest.fixture
def registry():
    return RoleRegistry.from_directory(ROLES_DIR)


def make_plan(**overrides) -> GraphWiringPlan:
    """Shared factory for creating test wiring plans."""
    defaults = {
        "goal": "test",
        "nodes": [
            {"id": "n1", "role": "rag_retriever"},
            {"id": "n2", "role": "schema_validator"},
        ],
        "edges": [{"source": "n1", "target": "n2"}],
        "entry_point": "n1",
        "role_versions": {
            "rag_retriever": "1.0.0",
            "schema_validator": "1.0.0",
        },
    }
    defaults.update(overrides)
    return GraphWiringPlan(**defaults)
