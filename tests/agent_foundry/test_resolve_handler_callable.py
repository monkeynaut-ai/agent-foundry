"""Tests for resolve_handler_callable — import, instantiate, resolve method."""

from unittest.mock import patch

import pytest

from agent_foundry.registry.errors import CapabilityImportError
from agent_foundry.registry.imports import resolve_handler_callable
from agent_foundry.registry.spec import CapabilitySpec, ImplementationPointer


def _make_spec(module, class_name, method="__call__"):
    return CapabilitySpec(
        name="test_cap",
        description="test",
        version="1.0.0",
        implementation=ImplementationPointer(
            module=module,
            class_name=class_name,
            method=method,
        ),
        inputs_schema={"type": "object", "properties": {}},
        outputs_schema={"type": "object", "properties": {}},
    )


class TestResolveHandlerCallable:
    def test_given_valid_pointer_with_default_method_when_resolved_then_returns_callable(self):
        spec = _make_spec("tests.agent_foundry.stub_handler", "StubHandler")
        handler = resolve_handler_callable(spec.implementation, spec)
        assert callable(handler)

    def test_given_valid_pointer_with_custom_method_when_resolved_then_returns_bound_method(self):
        spec = _make_spec(
            "tests.agent_foundry.stub_handler",
            "StubHandler",
            method="custom_method",
        )
        handler = resolve_handler_callable(spec.implementation, spec)
        assert callable(handler)

    def test_given_pointer_to_class_that_fails_init_when_resolved_then_raises_capability_import_error(
        self,
    ):
        spec = _make_spec("tests.agent_foundry.stub_handler", "BadInitHandler")
        with pytest.raises(CapabilityImportError) as exc_info:
            resolve_handler_callable(spec.implementation, spec)
        assert "BadInitHandler" in str(exc_info.value)

    def test_given_pointer_with_nonexistent_method_when_resolved_then_raises_capability_import_error(
        self,
    ):
        spec = _make_spec(
            "tests.agent_foundry.stub_handler",
            "StubHandler",
            method="no_such_method",
        )
        with pytest.raises(CapabilityImportError) as exc_info:
            resolve_handler_callable(spec.implementation, spec)
        assert "no_such_method" in str(exc_info.value)

    def test_given_feature_flag_off_when_resolved_then_returns_none(self):
        spec = _make_spec("tests.agent_foundry.stub_handler", "StubHandler")
        with patch("agent_foundry.registry.imports.FF_CAPABILITY_IMPORTS", False):
            result = resolve_handler_callable(spec.implementation, spec)
        assert result is None

    def test_given_resolved_callable_when_invoked_with_state_then_returns_expected_output(self):
        spec = _make_spec("tests.agent_foundry.stub_handler", "StubHandler")
        handler = resolve_handler_callable(spec.implementation, spec)
        result = handler({"input": "test"})
        assert result == {"input": "test", "handled": True}

    def test_given_resolved_custom_method_when_invoked_with_state_then_returns_expected_output(
        self,
    ):
        spec = _make_spec(
            "tests.agent_foundry.stub_handler",
            "StubHandler",
            method="custom_method",
        )
        handler = resolve_handler_callable(spec.implementation, spec)
        result = handler({"input": "test"})
        assert result == {"input": "test", "custom": True}
