"""Tests for ``agent_foundry.evals.api.registry_loader``."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from agent_foundry.evals.api.registry_loader import (
    InvalidRegistrySpecError,
    RegistryAttributeError,
    RegistryModuleImportError,
    load_registry,
)
from agent_foundry.evals.registry import AICallRegistry


@pytest.fixture()
def _make_registry_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Write a Python module that exposes an AICallRegistry instance."""

    def _factory(module_name: str, attr_name: str = "REG") -> str:
        module_path = tmp_path / f"{module_name}.py"
        module_path.write_text(
            textwrap.dedent(
                f"""
                from agent_foundry.evals.registry import AICallRegistry
                {attr_name} = AICallRegistry()
                """
            ).lstrip()
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        return f"{module_name}:{attr_name}"

    yield _factory

    # Ensure imported modules don't leak across tests.
    for name in list(sys.modules):
        if name.startswith("_loader_test_"):
            del sys.modules[name]


def test_load_registry_returns_instance(_make_registry_module) -> None:
    spec = _make_registry_module("_loader_test_basic")
    reg = load_registry(spec)
    assert isinstance(reg, AICallRegistry)


def test_load_registry_invalid_spec_no_colon() -> None:
    with pytest.raises(InvalidRegistrySpecError, match="module:attribute"):
        load_registry("no_colon_here")


def test_load_registry_invalid_spec_empty_module() -> None:
    with pytest.raises(InvalidRegistrySpecError):
        load_registry(":REGISTRY")


def test_load_registry_invalid_spec_empty_attr() -> None:
    with pytest.raises(InvalidRegistrySpecError):
        load_registry("module.path:")


def test_load_registry_module_not_found() -> None:
    with pytest.raises(RegistryModuleImportError):
        load_registry("does_not_exist_module_xyz:REGISTRY")


def test_load_registry_attribute_missing(_make_registry_module) -> None:
    # Module defines REG; ask for a different attribute name.
    _make_registry_module("_loader_test_attr_missing", attr_name="REG")
    with pytest.raises(RegistryAttributeError, match="MISSING"):
        load_registry("_loader_test_attr_missing:MISSING")


def test_load_registry_attribute_wrong_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_path = tmp_path / "_loader_test_wrong_type.py"
    module_path.write_text("REG = 42\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(TypeError, match="AICallRegistry"):
        load_registry("_loader_test_wrong_type:REG")
