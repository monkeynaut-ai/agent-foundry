"""Tests for dynamic handler resolution in the compiler via CapabilityRegistry."""

from typing import Any
from unittest.mock import patch

import pytest

from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.compiler.errors import CapabilityInstantiationError
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import CapabilityRegistry
from agent_foundry.registry.spec import (
    CapabilitySpec,
    ImplementationPointer,
)


def _make_spec(
    name, module, class_name, method="__call__", inputs_schema=None, outputs_schema=None
):
    return CapabilitySpec(
        name=name,
        description="test",
        version="1.0.0",
        implementation=ImplementationPointer(
            module=module,
            class_name=class_name,
            method=method,
        ),
        inputs_schema=inputs_schema or {"type": "object", "properties": {}},
        outputs_schema=outputs_schema or {"type": "object", "properties": {}},
    )


def _one_node_plan(capability="test_cap") -> GraphWiringPlan:
    return GraphWiringPlan(
        goal="test",
        nodes=[{"id": "n1", "capability": capability, "config": {}}],
        edges=[],
        entry_point="n1",
        capability_versions={capability: "1.0.0"},
    )


def _explicit_handler(state: dict[str, Any]) -> dict[str, Any]:
    return {**state, "explicit": True}


class TestExplicitHandlerPriority:
    def test_given_capability_in_explicit_registry_when_compiled_then_uses_explicit_handler(self):
        spec = _make_spec("test_cap", "tests.agent_foundry.stub_handler", "StubHandler")
        registry = CapabilityRegistry(specs={"test_cap": spec})
        handler_registry = {"test_cap": _explicit_handler}

        graph = compile_plan(_one_node_plan(), registry, handler_registry=handler_registry)
        result = graph.invoke({"input": "hello"})
        assert result["explicit"] is True

    def test_given_capability_in_both_registries_when_compiled_then_explicit_takes_priority(self):
        spec = _make_spec("test_cap", "tests.agent_foundry.stub_handler", "StubHandler")
        registry = CapabilityRegistry(specs={"test_cap": spec})
        handler_registry = {"test_cap": _explicit_handler}

        graph = compile_plan(_one_node_plan(), registry, handler_registry=handler_registry)
        result = graph.invoke({"input": "hello"})
        # Explicit handler sets "explicit", dynamic would set "handled"
        assert result["explicit"] is True
        assert "handled" not in result

    def test_given_explicit_handler_when_invoked_then_no_schema_validation_applied(self):
        spec = _make_spec(
            "test_cap",
            "tests.agent_foundry.stub_handler",
            "StubHandler",
            inputs_schema={
                "type": "object",
                "properties": {"required_field": {"type": "string"}},
                "required": ["required_field"],
            },
        )
        registry = CapabilityRegistry(specs={"test_cap": spec})
        handler_registry = {"test_cap": _explicit_handler}

        # Input lacks required_field, but explicit handlers skip validation
        graph = compile_plan(_one_node_plan(), registry, handler_registry=handler_registry)
        result = graph.invoke({"input": "hello"})
        assert result["explicit"] is True


class TestDynamicResolution:
    def test_given_capability_not_in_explicit_registry_but_in_capability_registry_when_compiled_then_dynamically_resolves(
        self,
    ):
        spec = _make_spec("test_cap", "tests.agent_foundry.stub_handler", "StubHandler")
        registry = CapabilityRegistry(specs={"test_cap": spec})

        graph = compile_plan(_one_node_plan(), registry)
        result = graph.invoke({"input": "hello"})
        assert result["handled"] is True

    def test_given_spec_with_custom_method_when_compiled_then_resolves_correct_method(self):
        spec = _make_spec(
            "test_cap",
            "tests.agent_foundry.stub_handler",
            "StubHandler",
            method="custom_method",
        )
        registry = CapabilityRegistry(specs={"test_cap": spec})

        graph = compile_plan(_one_node_plan(), registry)
        result = graph.invoke({"input": "hello"})
        assert result["custom"] is True

    def test_given_dynamically_resolved_handler_when_graph_invoked_then_handler_executes_correctly(
        self,
    ):
        spec = _make_spec("test_cap", "tests.agent_foundry.stub_handler", "StubHandler")
        registry = CapabilityRegistry(specs={"test_cap": spec})

        graph = compile_plan(_one_node_plan(), registry)
        result = graph.invoke({"key1": "val1", "key2": "val2"})
        assert result["key1"] == "val1"
        assert result["key2"] == "val2"
        assert result["handled"] is True


class TestDynamicResolutionWithSchemaValidation:
    def test_given_dynamically_resolved_handler_when_invoked_with_valid_input_then_schema_validation_passes(
        self,
    ):
        spec = _make_spec(
            "test_cap",
            "tests.agent_foundry.stub_handler",
            "StubHandler",
            inputs_schema={
                "type": "object",
                "properties": {"input": {"type": "string"}},
                "required": ["input"],
            },
            outputs_schema={"type": "object", "properties": {}},
        )
        registry = CapabilityRegistry(specs={"test_cap": spec})

        graph = compile_plan(_one_node_plan(), registry)
        result = graph.invoke({"input": "hello"})
        assert result["handled"] is True

    def test_given_dynamically_resolved_handler_when_invoked_with_invalid_input_then_raises_execution_error(
        self,
    ):
        spec = _make_spec(
            "test_cap",
            "tests.agent_foundry.stub_handler",
            "StubHandler",
            inputs_schema={
                "type": "object",
                "properties": {"required_field": {"type": "string"}},
                "required": ["required_field"],
            },
        )
        registry = CapabilityRegistry(specs={"test_cap": spec})

        graph = compile_plan(_one_node_plan(), registry)
        with pytest.raises(Exception) as exc_info:
            graph.invoke({"wrong_field": "hello"})
        # The CapabilityExecutionError gets wrapped by LangGraph, so check the cause chain
        assert "input_validation" in str(exc_info.value) or "required_field" in str(exc_info.value)


class TestFallbackToPassthrough:
    def test_given_capability_in_neither_registry_when_compiled_then_uses_passthrough(self):
        registry = CapabilityRegistry(specs={})

        graph = compile_plan(_one_node_plan(), registry)
        result = graph.invoke({"input": "hello"})
        # Passthrough returns state unchanged
        assert result == {"input": "hello"}


class TestDynamicResolutionErrors:
    def test_given_dynamic_resolution_fails_import_when_compiled_then_raises_capability_instantiation_error(
        self,
    ):
        spec = _make_spec("test_cap", "nonexistent.module", "BadClass")
        registry = CapabilityRegistry(specs={"test_cap": spec})

        with pytest.raises(CapabilityInstantiationError) as exc_info:
            compile_plan(_one_node_plan(), registry)
        assert exc_info.value.node_id == "n1"
        assert exc_info.value.capability == "test_cap"

    def test_given_feature_flag_off_when_compiled_then_falls_through_to_passthrough(self):
        spec = _make_spec("test_cap", "tests.agent_foundry.stub_handler", "StubHandler")
        registry = CapabilityRegistry(specs={"test_cap": spec})

        with patch("agent_foundry.registry.imports.FF_CAPABILITY_IMPORTS", False):
            graph = compile_plan(_one_node_plan(), registry)
        result = graph.invoke({"input": "hello"})
        assert result == {"input": "hello"}
