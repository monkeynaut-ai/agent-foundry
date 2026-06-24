"""Inference contract — provider abstract base, request, and tuning parameters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field

from agent_foundry.models.usage import TokenUsage


class ReasoningEffort(StrEnum):
    """Reasoning effort levels — the union accepted across providers.

    Not every provider accepts every level (e.g. Anthropic has no ``MINIMAL``);
    each provider normalizes to its own supported set. Using an enum rejects
    typos at construction rather than at the provider call.
    """

    NONE = "none"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


class InferenceParameters(BaseModel):
    """Tuning parameters for an inference call, independent of model and provider."""

    effort: ReasoningEffort | None = None
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


class InferenceResult(BaseModel):
    """Provider call result: the parsed typed output plus token usage.

    ``usage`` is ``None`` when the backend reported no usable token
    counts, so consumers degrade to "unknown" rather than crashing.
    Providers report tokens but no dollar cost — pricing is out of scope
    for the inference layer.
    """

    output: BaseModel
    usage: TokenUsage | None = None


class InferenceProvider(ABC):
    """A service object that calls an inference backend.

    Beyond the single ``__call__``, concrete providers own the backend
    client, the mapping from ``InferenceRequest`` into provider-specific
    inputs (headers, parameter names, tool-use shapes), response parsing,
    and any provider-specific lifecycle (e.g. closing the client).
    """

    @abstractmethod
    async def __call__(self, request: InferenceRequest) -> InferenceResult:
        """Execute one inference call and return output plus token usage."""

    @abstractmethod
    async def close(self) -> None:
        """Release any resources held by the provider."""

    def is_transient(self, exc: Exception) -> bool:
        """Return True if ``exc`` is a transient failure worth retrying.

        Transient means a retry of the same call could succeed (rate limits,
        timeouts, connection drops, 5xx). Persistent failures (auth, bad
        request, model-unavailable) return False so the caller fails over
        instead of hammering the same model. Each provider classifies its own
        SDK's exception taxonomy; the base default is conservative — unknown
        errors are treated as persistent (no retry).
        """
        return False
