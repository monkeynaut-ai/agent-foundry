"""Inference contract — provider protocol, request, and tuning parameters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field


class InferenceParameters(BaseModel):
    """Tuning parameters for an inference call, independent of model and provider."""

    effort: str | None = Field(default=None, min_length=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    thinking: bool | None = None


@dataclass
class InferenceRequest[O: BaseModel]:
    """Typed input to an inference provider call."""

    instructions: str
    prompt: str
    parameters: InferenceParameters
    output_type: type[O]


class InferenceProvider(Protocol):
    """Common interface for all inference provider callables."""

    async def __call__(self, request: InferenceRequest) -> BaseModel: ...
