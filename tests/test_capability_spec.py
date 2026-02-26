"""S1.1 — Load and validate a single capability spec (happy path).

Tests: parse + validate valid spec; assert field equality for both YAML and JSON.
"""

from pathlib import Path

import pytest

from agent_foundry.registry.spec import CapabilitySpec, load_capability_spec

FIXTURES = Path(__file__).parent / "fixtures"


class TestLoadYamlSpec:
    """Load and validate a capability spec from YAML."""

    def test_load_yaml_returns_capability_spec(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.yaml")
        assert isinstance(spec, CapabilitySpec)

    def test_yaml_name_field_equality(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.yaml")
        assert spec.name == "rag_retriever"

    def test_yaml_description_field_equality(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.yaml")
        assert spec.description == "Retrieves relevant documents using RAG pattern"

    def test_yaml_version_field_equality(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.yaml")
        assert spec.version == "1.0.0"

    def test_yaml_implementation_field_equality(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.yaml")
        assert spec.implementation.module == "agent_foundry.capabilities.rag_retriever"
        assert spec.implementation.class_name == "RagRetrieverCapability"

    def test_yaml_inputs_schema_field_equality(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.yaml")
        assert spec.inputs_schema["type"] == "object"
        assert "query" in spec.inputs_schema["properties"]
        assert spec.inputs_schema["required"] == ["query"]

    def test_yaml_outputs_schema_field_equality(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.yaml")
        assert spec.outputs_schema["type"] == "object"
        assert "snippets" in spec.outputs_schema["properties"]

    def test_yaml_tags_field_equality(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.yaml")
        assert spec.tags == ["retrieval", "rag", "search"]

    def test_yaml_quality_controls_field_equality(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.yaml")
        assert spec.quality_controls.timeout_seconds == 30
        assert spec.quality_controls.max_retries == 2


class TestLoadJsonSpec:
    """Load and validate a capability spec from JSON."""

    def test_load_json_returns_capability_spec(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.json")
        assert isinstance(spec, CapabilitySpec)

    def test_json_name_field_equality(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.json")
        assert spec.name == "structured_output_pydantic"

    def test_json_description_field_equality(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.json")
        assert spec.description == "Produces structured output validated by Pydantic models"

    def test_json_version_field_equality(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.json")
        assert spec.version == "1.0.0"

    def test_json_implementation_field_equality(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.json")
        assert spec.implementation.module == "agent_foundry.capabilities.structured_output"
        assert spec.implementation.class_name == "StructuredOutputCapability"

    def test_json_tags_field_equality(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.json")
        assert spec.tags == ["structured_output", "pydantic", "llm"]

    def test_json_quality_controls_field_equality(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.json")
        assert spec.quality_controls.timeout_seconds == 60
        assert spec.quality_controls.max_retries == 3


class TestRoundTrip:
    """Validate round-trip serialization preserves all fields."""

    def test_yaml_round_trip_no_field_loss(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.yaml")
        dumped = spec.model_dump()
        reconstructed = CapabilitySpec(**dumped)
        assert reconstructed == spec

    def test_json_round_trip_no_field_loss(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.json")
        dumped = spec.model_dump()
        reconstructed = CapabilitySpec(**dumped)
        assert reconstructed == spec

    def test_json_serialization_round_trip(self):
        spec = load_capability_spec(FIXTURES / "valid_capability.yaml")
        json_str = spec.model_dump_json()
        reconstructed = CapabilitySpec.model_validate_json(json_str)
        assert reconstructed == spec
