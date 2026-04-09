"""Tests for the Claude-Code-compatible JSON schema transformer."""

from enum import StrEnum
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, Field

from agent_foundry.acp.schema_tools import to_claude_code_schema


class _TrivialModel(BaseModel):
    name: str
    count: int = 0


class _InnerKind(StrEnum):
    A = "a"
    B = "b"


class _VariantA(BaseModel):
    kind: Literal[_InnerKind.A] = _InnerKind.A
    value_a: str


class _VariantB(BaseModel):
    kind: Literal[_InnerKind.B] = _InnerKind.B
    value_b: int


class _Discriminated(BaseModel):
    outcome: Annotated[_VariantA | _VariantB, Field(discriminator="kind")]


class _NestedContainer(BaseModel):
    trivial: _TrivialModel
    discriminated: _Discriminated


class TestToClaudeCodeSchema:
    def test_given_trivial_model_when_flattened_then_no_defs_or_refs(self):
        schema = to_claude_code_schema(_TrivialModel)
        text = str(schema)
        assert "$defs" not in schema
        assert "$ref" not in text
        assert schema["type"] == "object"
        assert "name" in schema["properties"]

    def test_given_discriminated_union_when_flattened_then_discriminator_stripped(self):
        schema = to_claude_code_schema(_Discriminated)
        assert "$defs" not in schema

        def _walk(node):
            if isinstance(node, dict):
                assert "discriminator" not in node
                assert "$ref" not in node
                for v in node.values():
                    _walk(v)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(schema)

    def test_given_discriminated_union_when_flattened_then_oneOf_preserved(self):
        schema = to_claude_code_schema(_Discriminated)
        outcome_prop = schema["properties"]["outcome"]
        assert "oneOf" in outcome_prop
        assert len(outcome_prop["oneOf"]) == 2
        for variant in outcome_prop["oneOf"]:
            assert variant["type"] == "object"
            assert "kind" in variant["properties"]
            assert variant["properties"]["kind"]["const"] in ("a", "b")

    def test_given_nested_model_with_inner_discriminated_union_then_all_levels_flattened(self):
        schema = to_claude_code_schema(_NestedContainer)
        trivial = schema["properties"]["trivial"]
        assert trivial["type"] == "object"
        assert "name" in trivial["properties"]
        discriminated = schema["properties"]["discriminated"]
        assert "oneOf" in discriminated["properties"]["outcome"]
        text = str(schema)
        assert "$ref" not in text
        assert "$defs" not in text

    def test_given_instance_dict_when_validated_against_flattened_schema_then_passes(self):
        try:
            import jsonschema
        except ImportError:
            pytest.skip("jsonschema not available")
        schema = to_claude_code_schema(_Discriminated)
        instance = {"outcome": {"kind": "a", "value_a": "hello"}}
        jsonschema.validate(instance, schema)
