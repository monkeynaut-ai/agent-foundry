"""AICall primitive — single LLM inference call with structured output."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, Field

from agent_foundry.ai_models.inference import InferenceParameters
from agent_foundry.ai_models.model import ModelEntry
from agent_foundry.primitives.models import Primitive


class ModelInput[I: BaseModel](BaseModel):
    """What the model reads: instructions (system prompt) and prompt (user message)."""

    instructions: str | Callable[[I], str]
    prompt: str | Callable[[I], str]


class AICall[I: BaseModel, O: BaseModel](Primitive[I, O], arbitrary_types_allowed=True):
    """Make a single LLM inference call and return structured output.

    A leaf primitive — no children, no tool loop. Returns an instance of O
    parsed from the model response.
    """

    model_input: ModelInput[I]
    model: ModelEntry | Callable[[I], ModelEntry]
    parameters: InferenceParameters | Callable[[I], InferenceParameters]
    timeout_seconds: int = Field(default=30, ge=1)


AICall.model_rebuild()
