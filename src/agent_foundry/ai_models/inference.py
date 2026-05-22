"""Inference contract — provider abstract base, request, and tuning parameters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from pydantic import BaseModel, Field


class InferenceParameters(BaseModel):
    """Tuning parameters for an inference call, independent of model and provider."""

    effort: str | None = Field(default=None, min_length=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    thinking: bool | None = None


@dataclass
class InferenceRequest[O: BaseModel]:
    """Typed input to an inference provider call.

    ``model_id`` is the provider-specific model identifier for this
    particular call.
    """

    model_id: str
    instructions: str
    prompt: str
    parameters: InferenceParameters
    output_type: type[O]


class InferenceProvider(ABC):
    """A service object that calls an inference backend.

    Beyond the single ``__call__``, concrete providers own the backend
    client, the mapping from ``InferenceRequest`` into provider-specific
    inputs (headers, parameter names, tool-use shapes), response parsing,
    and any provider-specific lifecycle (e.g. closing the client).
    """

    @abstractmethod
    async def __call__(self, request: InferenceRequest) -> BaseModel:
        """Execute one inference call and return the parsed typed output."""

    @abstractmethod
    async def close(self) -> None:
        """Release any resources held by the provider."""
