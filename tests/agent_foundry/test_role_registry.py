"""S1.3 — Multi-file registry initialization + duplicate detection.

Tests: load capabilities/*.(yaml|json), build RoleRegistry,
       deterministic duplicate-name detection.
"""

import shutil
from pathlib import Path

import pytest

from agent_foundry.registry.errors import DuplicateRoleError
from agent_foundry.registry.registry import RoleRegistry

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def roles_dir(tmp_path):
    """Create a temp roles directory with two distinct specs."""
    d = tmp_path / "capabilities"
    d.mkdir()
    shutil.copy(FIXTURES / "valid_role.yaml", d / "rag_retriever.yaml")
    shutil.copy(FIXTURES / "valid_role.json", d / "structured_output.json")
    return d


@pytest.fixture
def duplicate_dir(tmp_path):
    """Create a temp directory with two specs sharing the same name."""
    d = tmp_path / "capabilities"
    d.mkdir()
    shutil.copy(FIXTURES / "valid_role.yaml", d / "rag_retriever_1.yaml")
    shutil.copy(FIXTURES / "valid_role.yaml", d / "rag_retriever_2.yaml")
    return d


class TestRegistryInitialization:
    """Registry loads all specs from a directory."""

    def test_registry_loads_all_specs(self, roles_dir):
        registry = RoleRegistry.from_directory(roles_dir)
        assert len(registry) == 2

    def test_registry_contains_yaml_spec(self, roles_dir):
        registry = RoleRegistry.from_directory(roles_dir)
        assert registry.get("rag_retriever") is not None

    def test_registry_contains_json_spec(self, roles_dir):
        registry = RoleRegistry.from_directory(roles_dir)
        assert registry.get("structured_output_pydantic") is not None

    def test_registry_get_unknown_returns_none(self, roles_dir):
        registry = RoleRegistry.from_directory(roles_dir)
        assert registry.get("nonexistent") is None

    def test_empty_directory_creates_empty_registry(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        registry = RoleRegistry.from_directory(d)
        assert len(registry) == 0

    def test_registry_names_returns_all_names(self, roles_dir):
        registry = RoleRegistry.from_directory(roles_dir)
        names = registry.names()
        assert sorted(names) == ["rag_retriever", "structured_output_pydantic"]


class TestDuplicateDetection:
    """Duplicate role names are detected deterministically."""

    def test_duplicate_name_raises_error(self, duplicate_dir):
        with pytest.raises(DuplicateRoleError):
            RoleRegistry.from_directory(duplicate_dir)

    def test_duplicate_error_includes_both_paths(self, duplicate_dir):
        with pytest.raises(DuplicateRoleError) as exc_info:
            RoleRegistry.from_directory(duplicate_dir)
        err = exc_info.value
        assert err.role_name == "rag_retriever"
        assert len(err.file_paths) == 2

    def test_duplicate_error_message_is_descriptive(self, duplicate_dir):
        with pytest.raises(DuplicateRoleError) as exc_info:
            RoleRegistry.from_directory(duplicate_dir)
        msg = str(exc_info.value)
        assert "rag_retriever" in msg
