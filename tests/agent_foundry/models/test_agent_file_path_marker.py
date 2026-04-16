"""Tests for the AgentFilePath Annotated metadata marker."""

from __future__ import annotations

import dataclasses
from typing import Annotated

import pytest
from pydantic import BaseModel

from agent_foundry.models.markers import (
    PLATFORM_DEFAULT_MAX_FILE_BYTES,
    AgentFilePath,
    FilePathFieldSpec,
    extract_paths,
    walk_file_path_fields,
)

# ======================================================================
# Defaults and custom construction
# ======================================================================


def test_platform_default_max_file_bytes_constant() -> None:
    assert PLATFORM_DEFAULT_MAX_FILE_BYTES == 10_000_000


def test_agent_file_path_defaults_to_platform_max() -> None:
    marker = AgentFilePath()
    assert marker.max_size_bytes == PLATFORM_DEFAULT_MAX_FILE_BYTES
    assert marker.max_size_bytes == 10_000_000


def test_agent_file_path_accepts_custom_max_size() -> None:
    marker = AgentFilePath(max_size_bytes=50_000_000)
    assert marker.max_size_bytes == 50_000_000


# ======================================================================
# Frozen dataclass semantics
# ======================================================================


def test_agent_file_path_is_frozen_dataclass() -> None:
    marker = AgentFilePath()
    with pytest.raises(dataclasses.FrozenInstanceError):
        marker.max_size_bytes = 123  # type: ignore[misc]


# ======================================================================
# Pydantic JSON schema propagation
# ======================================================================


class _DefaultModel(BaseModel):
    review_path: Annotated[str, AgentFilePath()]


class _CustomModel(BaseModel):
    transcript_path: Annotated[str, AgentFilePath(max_size_bytes=50_000_000)]


class _ListModel(BaseModel):
    paths: list[Annotated[str, AgentFilePath()]]


def _field_schema(model_cls: type[BaseModel], field_name: str) -> dict:
    schema = model_cls.model_json_schema()
    return schema["properties"][field_name]


def test_default_marker_emits_x_agent_file_path_in_schema() -> None:
    field_schema = _field_schema(_DefaultModel, "review_path")
    assert "x-agent-file-path" in field_schema
    assert field_schema["x-agent-file-path"] == {"max_size_bytes": PLATFORM_DEFAULT_MAX_FILE_BYTES}


def test_custom_max_size_propagates_into_schema() -> None:
    field_schema = _field_schema(_CustomModel, "transcript_path")
    assert field_schema["x-agent-file-path"] == {"max_size_bytes": 50_000_000}


def test_marker_inside_list_propagates_at_item_level() -> None:
    field_schema = _field_schema(_ListModel, "paths")
    assert field_schema["type"] == "array"
    items_schema = field_schema["items"]
    assert "x-agent-file-path" in items_schema
    assert items_schema["x-agent-file-path"] == {"max_size_bytes": PLATFORM_DEFAULT_MAX_FILE_BYTES}
    # And the outer array schema should NOT carry the marker.
    assert "x-agent-file-path" not in field_schema


# ======================================================================
# walk_file_path_fields — schema walker
# ======================================================================


class _ReviewerOutput(BaseModel):
    review_path: Annotated[str, AgentFilePath()]
    summary: str


class _CustomSizeOutput(BaseModel):
    transcript_path: Annotated[str, AgentFilePath(max_size_bytes=50_000_000)]


class _Inner(BaseModel):
    inner_path: Annotated[str, AgentFilePath()]


class _Outer(BaseModel):
    inner: _Inner


class _ListPathsOutput(BaseModel):
    paths: list[Annotated[str, AgentFilePath()]]


class _UnmarkedOutput(BaseModel):
    title: str
    count: int


class _MixedOutput(BaseModel):
    review_path: Annotated[str, AgentFilePath()]
    transcript_path: Annotated[str, AgentFilePath(max_size_bytes=50_000_000)]
    summary: str


def test_walk_file_path_fields_flat_object_finds_single_spec() -> None:
    specs = walk_file_path_fields(_ReviewerOutput.model_json_schema())
    assert len(specs) == 1
    (spec,) = specs
    assert isinstance(spec, FilePathFieldSpec)
    assert spec.json_pointer == "/review_path"
    assert spec.max_size_bytes == PLATFORM_DEFAULT_MAX_FILE_BYTES


def test_walk_file_path_fields_propagates_custom_max_size() -> None:
    specs = walk_file_path_fields(_CustomSizeOutput.model_json_schema())
    assert len(specs) == 1
    assert specs[0].json_pointer == "/transcript_path"
    assert specs[0].max_size_bytes == 50_000_000


def test_walk_file_path_fields_handles_nested_objects() -> None:
    # Pydantic serializes nested models via $defs/$ref — the walker
    # must resolve refs to find markers in the nested schema.
    specs = walk_file_path_fields(_Outer.model_json_schema())
    pointers = {s.json_pointer for s in specs}
    assert "/inner/inner_path" in pointers


def test_walk_file_path_fields_handles_list_of_paths_with_wildcard() -> None:
    specs = walk_file_path_fields(_ListPathsOutput.model_json_schema())
    assert len(specs) == 1
    assert specs[0].json_pointer == "/paths/*"
    assert specs[0].max_size_bytes == PLATFORM_DEFAULT_MAX_FILE_BYTES


def test_walk_file_path_fields_returns_empty_when_no_marker() -> None:
    specs = walk_file_path_fields(_UnmarkedOutput.model_json_schema())
    assert specs == []


def test_walk_file_path_fields_resolves_defs_and_refs() -> None:
    # _Outer's schema uses $defs + $ref for the nested _Inner model.
    # Confirm the walker still locates the marker through the ref.
    schema = _Outer.model_json_schema()
    assert "$defs" in schema  # sanity: schema actually uses $defs
    specs = walk_file_path_fields(schema)
    pointers = {s.json_pointer for s in specs}
    assert "/inner/inner_path" in pointers


# ======================================================================
# extract_paths — resolve JSON pointers against an output instance
# ======================================================================


def test_extract_paths_flat_single_field() -> None:
    specs = [FilePathFieldSpec(json_pointer="/review_path", max_size_bytes=10_000_000)]
    output = {"review_path": "/workspace/r.md"}
    result = extract_paths(output, specs)
    assert result == [("/workspace/r.md", 10_000_000)]


def test_extract_paths_list_wildcard_expands_each_item() -> None:
    specs = [FilePathFieldSpec(json_pointer="/paths/*", max_size_bytes=10_000_000)]
    output = {"paths": ["/a.md", "/b.md"]}
    result = extract_paths(output, specs)
    assert result == [("/a.md", 10_000_000), ("/b.md", 10_000_000)]


def test_extract_paths_skips_missing_optional_field() -> None:
    # Plan: "Missing optional nodes are silently skipped."
    specs = [FilePathFieldSpec(json_pointer="/review_path", max_size_bytes=10_000_000)]
    result = extract_paths({}, specs)
    assert result == []


def test_extract_paths_mixed_specs_resolve_independently() -> None:
    specs = [
        FilePathFieldSpec(json_pointer="/review_path", max_size_bytes=10_000_000),
        FilePathFieldSpec(json_pointer="/transcript_path", max_size_bytes=50_000_000),
    ]
    output = {
        "review_path": "/workspace/r.md",
        "transcript_path": "/workspace/t.md",
        "summary": "ignore me",
    }
    result = extract_paths(output, specs)
    assert ("/workspace/r.md", 10_000_000) in result
    assert ("/workspace/t.md", 50_000_000) in result
    assert len(result) == 2


def test_extract_paths_empty_list_wildcard_yields_no_entries() -> None:
    specs = [FilePathFieldSpec(json_pointer="/paths/*", max_size_bytes=10_000_000)]
    result = extract_paths({"paths": []}, specs)
    assert result == []


def test_extract_paths_nested_pointer() -> None:
    specs = [FilePathFieldSpec(json_pointer="/inner/inner_path", max_size_bytes=10_000_000)]
    output = {"inner": {"inner_path": "/workspace/deep.md"}}
    result = extract_paths(output, specs)
    assert result == [("/workspace/deep.md", 10_000_000)]


def test_filepathfieldspec_is_frozen_dataclass() -> None:
    spec = FilePathFieldSpec(json_pointer="/p", max_size_bytes=100)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.json_pointer = "/q"  # type: ignore[misc]
