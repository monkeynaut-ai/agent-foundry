"""Tests for the AgentFilePath Annotated metadata marker (Task D.1)."""

from __future__ import annotations

import dataclasses
from typing import Annotated

import pytest
from pydantic import BaseModel

from agent_foundry.models.markers import (
    PLATFORM_DEFAULT_MAX_FILE_BYTES,
    AgentFilePath,
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
