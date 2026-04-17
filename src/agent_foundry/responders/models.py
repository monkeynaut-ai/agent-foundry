"""Responder request/response models.

These models define the boundary contract between agent turn outcomes
(ClarificationOutcome, PermissionOutcome) and the human-in-the-loop
responder interface. ``build_request_from_outcome`` maps outcomes to
responder requests, attaching the agent identity and turn coordinates.

Kind values use ``StrEnum`` (project convention) but the discriminator
fields on each request class are wrapped with
``Literal[ResponderKind.VARIANT]``. This is the explicit fallback clause
in the project's data-model rules: Pydantic v2.12 rejects bare
``StrEnum``-typed discriminator fields. The ``Literal[SomeEnum.VARIANT]``
form preserves the enum as source of truth while satisfying Pydantic's
discriminator requirement.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_foundry.acp.agent_turn_envelope import (
    ClarificationOutcome,
    PermissionOutcome,
)


class ResponderKind(StrEnum):
    CLARIFICATION = "clarification"
    PERMISSION = "permission"


class ClarificationRequest(BaseModel):
    kind: Literal[ResponderKind.CLARIFICATION] = ResponderKind.CLARIFICATION
    question: str = Field(min_length=1)
    options: list[str] = Field(default_factory=list)
    agent_name: str = Field(min_length=1)
    invocation: int = Field(ge=0)
    turn: int = Field(ge=0)


class PermissionRequest(BaseModel):
    kind: Literal[ResponderKind.PERMISSION] = ResponderKind.PERMISSION
    action_summary: str = Field(min_length=1)
    risk_level: str = Field(min_length=1)
    why_needed: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    invocation: int = Field(ge=0)
    turn: int = Field(ge=0)


ResponderRequest = Annotated[
    ClarificationRequest | PermissionRequest,
    Field(discriminator="kind"),
]


class ResponderResponse(BaseModel):
    answer: str


class ResponderContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    invocation: int = Field(ge=0)
    turn: int = Field(ge=0)


def build_request_from_outcome(
    outcome: ClarificationOutcome | PermissionOutcome,
    *,
    agent_name: str,
    invocation: int,
    turn: int,
) -> ResponderRequest:
    """Map a turn outcome to the corresponding responder request.

    Uses ``is``-based exact-type dispatch (not ``isinstance``) to honor
    the project rule against accepting subclasses at model boundaries.
    """
    if type(outcome) is ClarificationOutcome:
        return ClarificationRequest(
            question=outcome.question,
            options=list(outcome.options),
            agent_name=agent_name,
            invocation=invocation,
            turn=turn,
        )
    if type(outcome) is PermissionOutcome:
        return PermissionRequest(
            action_summary=outcome.action,
            risk_level=outcome.risk_level,
            why_needed=outcome.why_needed,
            agent_name=agent_name,
            invocation=invocation,
            turn=turn,
        )
    raise TypeError(f"Unsupported outcome type: {type(outcome).__name__}")
