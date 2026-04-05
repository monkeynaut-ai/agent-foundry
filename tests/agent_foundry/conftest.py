"""Shared fixtures for agent_foundry tests."""

from pathlib import Path

import pytest

from agent_foundry.registry.registry import RoleRegistry

ROLES_DIR = Path(__file__).parent.parent.parent / "src" / "agent_foundry" / "roles"


@pytest.fixture
def registry():
    return RoleRegistry.from_directory(ROLES_DIR)
