"""AIRequest primitive — single LLM inference call with structured output."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from agent_foundry.primitives.models import Primitive


class InferenceProvider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class ModelInput[I: BaseModel](BaseModel):
    """What the model reads: instructions (system prompt) and prompt (user message)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    instructions: str | Callable[[I], str]
    prompt: str | Callable[[I], str]


class ModelConfiguration(BaseModel):
    """Parameters that configure how the model runs, regardless of provider or executor."""

    model: str = Field(min_length=1)
    effort: str | None = Field(default=None, min_length=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    thinking: bool | None = None


class AIRequest[I: BaseModel, O: BaseModel](Primitive[I, O]):
    """Make a single LLM inference call and return structured output.

    A leaf primitive — no children, no tool loop. Returns an instance of O
    parsed from the model response.

    When ``model_configuration`` is a callable, it is called with the current
    state at runtime to produce the configuration for that invocation.
    """

    model_input: ModelInput[I]
    model_configuration: ModelConfiguration | Callable[[I], ModelConfiguration]
    provider: InferenceProvider
    timeout_seconds: int = Field(default=30, ge=1)


AIRequest.model_rebuild()
