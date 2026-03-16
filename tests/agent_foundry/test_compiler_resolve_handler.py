"""Tests for _resolve_handler fallback paths in the compiler."""

import pytest

from agent_foundry.compiler.compiler import _resolve_handler
from agent_foundry.compiler.errors import RoleInstantiationError
from agent_foundry.registry.registry import RoleRegistry
from agent_foundry.registry.spec import RoleSpec, ImplementationPointer


def _make_spec(
    name: str, module: str = "tests.agent_foundry.stub_handler", class_name: str = "StubHandler"
):
    return RoleSpec(
        name=name,
        description="test",
        version="1.0.0",
        implementation=ImplementationPointer(module=module, class_name=class_name),
        inputs_schema={"type": "object", "properties": {}},
        outputs_schema={"type": "object", "properties": {}},
    )


class TestResolveHandler:
    def test_given_role_in_handler_registry_then_returns_that_handler(self):
        handler = lambda state: state  # noqa: E731
        result = _resolve_handler("n1", "test_cap", {"test_cap": handler}, RoleRegistry(specs={}))
        assert result is handler

    def test_given_non_callable_in_handler_registry_then_raises_instantiation_error(self):
        with pytest.raises(RoleInstantiationError) as exc_info:
            _resolve_handler("n1", "test_cap", {"test_cap": "not_callable"}, RoleRegistry(specs={}))
        assert exc_info.value.node_id == "n1"

    def test_given_role_not_in_handler_registry_but_valid_in_registry_then_dynamic_import(
        self,
    ):
        spec = _make_spec("test_cap")
        registry = RoleRegistry(specs={"test_cap": spec})
        handler = _resolve_handler("n1", "test_cap", {}, registry)
        # Should return a validated handler wrapper (callable)
        assert callable(handler)
        result = handler({"input": "hello"})
        assert result["handled"] is True

    def test_given_role_not_in_handler_registry_and_import_fails_then_raises_instantiation_error(
        self,
    ):
        spec = _make_spec("test_cap", module="nonexistent.module", class_name="Bad")
        registry = RoleRegistry(specs={"test_cap": spec})
        with pytest.raises(RoleInstantiationError) as exc_info:
            _resolve_handler("n1", "test_cap", {}, registry)
        assert exc_info.value.role == "test_cap"

    def test_given_role_nowhere_then_returns_passthrough_handler(self):
        handler = _resolve_handler("n1", "unknown_cap", {}, RoleRegistry(specs={}))
        assert callable(handler)
        result = handler({"key": "value"})
        assert result == {"key": "value"}
