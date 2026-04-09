"""Generic turn-outcome envelope for agents running Claude Code in headless mode.

Every agent running under Claude Code's --json-schema returns its turn result
as an AgentTurnEnvelope[T], where T is the agent-specific success payload.
The envelope's outcome field is a discriminated union of four variants:

    - SuccessOutcome[T]      — normal completion with typed payload
    - ClarificationOutcome   — agent needs human input to proceed
    - PermissionOutcome      — agent needs approval to proceed
    - FailureOutcome         — agent declares the task cannot be completed

This envelope lives in Agent Foundry because the four outcome kinds are
properties of Claude Code headless execution, not any particular domain.
The generic parameter T lets each consumer bring its own payload type.
Consumers inject the schema into `claude --json-schema` by calling
``to_claude_code_schema(AgentTurnEnvelope[PayloadType])`` directly.

Rationale notes:
    - FailureOutcome uses a free-form `reason: str` — no FailureCategory
      enum. Consumers promote patterns to an enum later if field data
      justifies it.
    - Kind values use StrEnum (per project convention) but are wrapped with
      ``Literal[TurnOutcomeKind.VARIANT]`` on each outcome class. This is
      the project rule's explicit fallback clause: Pydantic v2.12 rejects
      bare StrEnum-typed discriminator fields with
      ``PydanticUserError: Model 'X' needs field 'kind' to be of type
      'Literal'``. Empirically verified in the CS6.5 planning session.
      The ``Literal[SomeEnum.VARIANT]`` form preserves the enum as the
      source of truth while satisfying Pydantic's discriminator
      requirement.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class TurnOutcomeKind(StrEnum):
    SUCCESS = "success"
    CLARIFICATION_NEEDED = "clarification_needed"
    PERMISSION_NEEDED = "permission_needed"
    FAILED = "failed"


class SuccessOutcome[T: BaseModel](BaseModel):
    kind: Literal[TurnOutcomeKind.SUCCESS] = TurnOutcomeKind.SUCCESS
    payload: T


class ClarificationOutcome(BaseModel):
    kind: Literal[TurnOutcomeKind.CLARIFICATION_NEEDED] = TurnOutcomeKind.CLARIFICATION_NEEDED
    question: str = Field(description="What the agent needs to know to proceed")
    options: list[str] = Field(
        default_factory=list,
        description="Possible answers the human can pick from, if applicable",
    )
    blocking: bool = Field(
        default=True,
        description="Whether the agent must receive an answer before continuing",
    )


class PermissionOutcome(BaseModel):
    kind: Literal[TurnOutcomeKind.PERMISSION_NEEDED] = TurnOutcomeKind.PERMISSION_NEEDED
    action: str = Field(description="Action the agent wants to take")
    risk_level: str = Field(description="Suggested taxonomy: low | medium | high")
    why_needed: str = Field(description="Why the action is necessary for the task")


class FailureOutcome(BaseModel):
    kind: Literal[TurnOutcomeKind.FAILED] = TurnOutcomeKind.FAILED
    reason: str = Field(
        description="Why the agent cannot proceed and why clarification/permission will not help"
    )
    attempted_approaches: list[str] = Field(
        default_factory=list,
        description="If the agent tried multiple approaches before giving up, list them here",
    )


class AgentTurnEnvelope[T: BaseModel](BaseModel):
    """Top-level envelope wrapping the discriminated outcome.

    Wrapping the union in an object with a single `outcome` field is required
    because Claude Code's --json-schema enforcement requires the top-level
    schema to be an object type; top-level oneOf is silently ignored.
    """

    outcome: Annotated[
        SuccessOutcome[T] | ClarificationOutcome | PermissionOutcome | FailureOutcome,
        Field(discriminator="kind"),
    ]
