"""S1.1 — Load and validate a single role spec (happy path)."""

from pathlib import Path

import pytest

from agent_foundry.registry.spec import RoleSpec, load_role_spec

FIXTURES = Path(__file__).parent / "fixtures"

SPEC_CASES = [
    (
        "yaml",
        FIXTURES / "valid_role.yaml",
        {
            "name": "rag_retriever",
            "description": "Retrieves relevant documents using RAG pattern",
            "version": "1.0.0",
            "implementation_module": "agent_foundry.roles.rag_retriever",
            "implementation_class": "RagRetrieverRole",
            "tags": ["retrieval", "rag", "search"],
            "timeout_seconds": 30,
            "max_retries": 2,
            "inputs_required": ["query"],
            "output_field": "snippets",
        },
    ),
    (
        "json",
        FIXTURES / "valid_role.json",
        {
            "name": "structured_output_pydantic",
            "description": "Produces structured output validated by Pydantic models",
            "version": "1.0.0",
            "implementation_module": "agent_foundry.roles.structured_output",
            "implementation_class": "StructuredOutputRole",
            "tags": ["structured_output", "pydantic", "llm"],
            "timeout_seconds": 60,
            "max_retries": 3,
            "inputs_required": None,
            "output_field": None,
        },
    ),
]


def _assert_spec_fields(spec: RoleSpec, expected: dict) -> None:
    assert spec.name == expected["name"]
    assert spec.description == expected["description"]
    assert spec.version == expected["version"]
    assert spec.implementation.module == expected["implementation_module"]
    assert spec.implementation.class_name == expected["implementation_class"]
    assert spec.tags == expected["tags"]
    assert spec.quality_controls.timeout_seconds == expected["timeout_seconds"]
    assert spec.quality_controls.max_retries == expected["max_retries"]

    if expected["inputs_required"] is not None:
        assert spec.inputs_schema["type"] == "object"
        assert spec.inputs_schema["required"] == expected["inputs_required"]

    if expected["output_field"] is not None:
        assert spec.outputs_schema["type"] == "object"
        assert expected["output_field"] in spec.outputs_schema["properties"]


@pytest.mark.parametrize("_, path, expected", SPEC_CASES)
def test_load_spec_returns_role_spec(_, path, expected):
    spec = load_role_spec(path)
    assert isinstance(spec, RoleSpec)
    _assert_spec_fields(spec, expected)


@pytest.mark.parametrize("_, path, _expected", SPEC_CASES)
def test_model_dump_round_trip(_, path, _expected):
    spec = load_role_spec(path)
    dumped = spec.model_dump()
    reconstructed = RoleSpec(**dumped)
    assert reconstructed == spec


def test_json_serialization_round_trip():
    spec = load_role_spec(FIXTURES / "valid_role.yaml")
    json_str = spec.model_dump_json()
    reconstructed = RoleSpec.model_validate_json(json_str)
    assert reconstructed == spec
