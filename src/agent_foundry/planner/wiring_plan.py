"""GraphWiringPlan Pydantic models — machine-compilable plan schema."""

from typing import Any

from pydantic import BaseModel, Field


class NodeDef(BaseModel):
    """A node in the wiring plan."""

    id: str
    role: str
    config: dict[str, Any] = Field(default_factory=dict)


class EdgeDef(BaseModel):
    """An edge connecting two nodes."""

    source: str
    target: str
    condition: str | None = None


class ToolDef(BaseModel):
    """A tool available to tool_calling nodes."""

    name: str
    args_schema: dict[str, Any] = Field(default_factory=dict)


class PersistenceConfig(BaseModel):
    """Persistence configuration for checkpointing."""

    backend: str
    thread_id: str


class GraphWiringPlan(BaseModel):
    """Machine-compilable graph wiring plan."""

    goal: str
    nodes: list[NodeDef]
    edges: list[EdgeDef]
    entry_point: str
    role_versions: dict[str, str] = Field(default_factory=dict)
    tools: list[ToolDef] = Field(default_factory=list)
    breakpoints: list[str] = Field(default_factory=list)
    persistence: PersistenceConfig | None = None
