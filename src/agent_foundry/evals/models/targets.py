"""Eval target variants — what gets evaluated.

A target is the entity under evaluation. ``AgentTarget`` wraps an
:class:`AgentAction` for evaluation through the full container-backed
orchestration path. ``AICallTarget`` wraps an :class:`AICall` for
evaluation through :func:`invoke_ai_call`, no container or
orchestration.

The two share the runner contract and reporting machinery; only the
mechanism of execution differs.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_foundry.primitives.ai_call import AICall
from agent_foundry.primitives.models import AgentAction


class EvalTargetKind(StrEnum):
    """Discriminator value for eval target variants."""

    AGENT = "agent"
    AI_CALL = "ai_call"


class AgentTarget(BaseModel):
    """Eval target backed by a multi-turn containerized agent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: Literal[EvalTargetKind.AGENT] = EvalTargetKind.AGENT
    agent: AgentAction


class AICallTarget(BaseModel):
    """Eval target backed by a single ``AICall`` declaration."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: Literal[EvalTargetKind.AI_CALL] = EvalTargetKind.AI_CALL
    ai_call: AICall


type EvalTarget = Annotated[AgentTarget | AICallTarget, Field(discriminator="kind")]
