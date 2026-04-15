"""Shared Pydantic models and metadata markers for agent-foundry."""

from __future__ import annotations

from agent_foundry.models.markers import (
    PLATFORM_DEFAULT_MAX_FILE_BYTES,
    AgentFilePath,
    FilePathFieldSpec,
    extract_paths,
    walk_file_path_fields,
)

__all__ = [
    "PLATFORM_DEFAULT_MAX_FILE_BYTES",
    "AgentFilePath",
    "FilePathFieldSpec",
    "extract_paths",
    "walk_file_path_fields",
]
