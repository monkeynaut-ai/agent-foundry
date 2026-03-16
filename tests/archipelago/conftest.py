"""Shared fixtures for archipelago tests."""

from pathlib import Path

import pytest

from agent_foundry.registry.registry import RoleRegistry

PRODUCT_ROLES_DIR = Path(__file__).parent.parent.parent / "src" / "archipelago" / "roles"


@pytest.fixture
def registry():
    return RoleRegistry.with_product_specs(PRODUCT_ROLES_DIR)
