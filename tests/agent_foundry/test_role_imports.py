"""S1.4 — Importable implementation pointers + instantiation failure reporting.

Tests: bad module path -> RoleImportError with pointer + underlying exception.
Feature flag: FF_CAPABILITY_IMPORTS (default on).
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from agent_foundry.registry.errors import RoleImportError
from agent_foundry.registry.imports import import_role_class
from agent_foundry.registry.spec import ImplementationPointer


class TestImportResolution:
    """Resolve implementation pointers to Python classes."""

    def test_valid_import_resolves_class(self):
        pointer = ImplementationPointer(
            module="pathlib",
            class_name="Path",
        )
        cls = import_role_class(pointer)
        assert cls is Path

    def test_bad_module_raises_import_error(self):
        pointer = ImplementationPointer(
            module="nonexistent.module.path",
            class_name="SomeClass",
        )
        with pytest.raises(RoleImportError) as exc_info:
            import_role_class(pointer)
        err = exc_info.value
        assert err.pointer == pointer
        assert err.__cause__ is not None

    def test_bad_class_name_raises_import_error(self):
        pointer = ImplementationPointer(
            module="pathlib",
            class_name="NonExistentClassName",
        )
        with pytest.raises(RoleImportError) as exc_info:
            import_role_class(pointer)
        err = exc_info.value
        assert err.pointer == pointer

    def test_import_error_message_includes_module(self):
        pointer = ImplementationPointer(
            module="totally.fake.module",
            class_name="Foo",
        )
        with pytest.raises(RoleImportError) as exc_info:
            import_role_class(pointer)
        assert "totally.fake.module" in str(exc_info.value)

    def test_import_error_message_includes_class_name(self):
        pointer = ImplementationPointer(
            module="pathlib",
            class_name="DoesNotExist",
        )
        with pytest.raises(RoleImportError) as exc_info:
            import_role_class(pointer)
        assert "DoesNotExist" in str(exc_info.value)


class TestFeatureFlag:
    """FF_CAPABILITY_IMPORTS controls import resolution."""

    def test_flag_off_skips_import(self):
        pointer = ImplementationPointer(
            module="nonexistent.module",
            class_name="Foo",
        )
        with patch("agent_foundry.registry.imports.FF_CAPABILITY_IMPORTS", False):
            result = import_role_class(pointer)
        assert result is None

    def test_flag_on_performs_import(self):
        pointer = ImplementationPointer(
            module="pathlib",
            class_name="Path",
        )
        with patch("agent_foundry.registry.imports.FF_CAPABILITY_IMPORTS", True):
            cls = import_role_class(pointer)
        assert cls is Path
