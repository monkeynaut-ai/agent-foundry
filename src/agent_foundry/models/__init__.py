"""Shared Pydantic models and metadata markers for agent-foundry."""

from __future__ import annotations

from agent_foundry.models.markers import (
    PLATFORM_DEFAULT_MAX_FILE_BYTES,
    AgentFilePath,
)

__all__ = [
    "PLATFORM_DEFAULT_MAX_FILE_BYTES",
    "AgentFilePath",
]
