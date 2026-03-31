"""GraphWiringPlan Pydantic models — machine-compilable plan schema."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class StateMappingDef(BaseModel):
    """Maps state keys between parent and subgraph boundaries."""

    input: dict[str, str] = Field(default_factory=dict)
    output: dict[str, str] = Field(default_factory=dict)


class NodeDef(BaseModel):
    """A node in the wiring plan.

    A node must have either a ``role`` (referencing a registered role) or a
    ``subgraph`` (an inline sub-plan), but not both.
    """

    id: str
    role: str | None = None
    subgraph: GraphWiringPlan | None = None
    state_mapping: StateMappingDef | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    inputs_schema: dict[str, Any] = Field(default_factory=dict)
    outputs_schema: dict[str, Any] = Field(default_factory=dict)
    inputs: list[str] = Field(
        default_factory=list,
        description="Type names declaring what the agent consumes",
    )
    outputs: list[str] = Field(
        default_factory=list,
        description="Type names declaring what the agent produces",
    )

    @model_validator(mode="after")
    def _role_xor_subgraph(self) -> NodeDef:
        if self.role is not None and self.subgraph is not None:
            raise ValueError(f"Node '{self.id}': 'role' and 'subgraph' are mutually exclusive")
        if self.role is None and self.subgraph is None:
            raise ValueError(f"Node '{self.id}': must have either 'role' or 'subgraph'")
        if self.subgraph is not None and self.state_mapping is None:
            raise ValueError(
                f"Node '{self.id}': 'state_mapping' is required when 'subgraph' is set"
            )
        return self


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
    state_schema: dict[str, Any]
    role_versions: dict[str, str] = Field(default_factory=dict)
    tools: list[ToolDef] = Field(default_factory=list)
    breakpoints: list[str] = Field(default_factory=list)
    persistence: PersistenceConfig | None = None


# Resolve forward references for the recursive NodeDef -> GraphWiringPlan relationship.
NodeDef.model_rebuild()
