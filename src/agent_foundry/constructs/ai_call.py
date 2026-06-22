"""AICall construct — single LLM inference call with structured output."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

from agent_foundry.ai_models.inference import InferenceParameters
from agent_foundry.ai_models.model import ModelEntry
from agent_foundry.constructs.models import Construct


class ModelInput[I: BaseModel](BaseModel):
    """What the model reads: instructions (system prompt) and prompt (user message)."""

    instructions: str | Callable[[I], str]
    prompt: str | Callable[[I], str]


class AICall[I: BaseModel, O: BaseModel](Construct[I, O], arbitrary_types_allowed=True):
    """Make a single LLM inference call and return structured output.

    A leaf construct — no children, no tool loop. Returns an instance of O
    parsed from the model response.
    """

    model_input: ModelInput[I]
    model: ModelEntry | Callable[[I], ModelEntry]
    parameters: InferenceParameters | Callable[[I], InferenceParameters]
    timeout_seconds: int = Field(default=30, ge=1)
    name: str | None = Field(default=None, min_length=1)
    """Diagnostic label for lifecycle events, spans, and logs. Not used for
    composition or lookup. Optional — when None the compiler falls back to the
    positional node_id."""
    executor: Callable[..., Awaitable[O]] | None = None
    """Async callable that performs the inference call.

    When None, the compiler uses ``invoke_ai_call`` (the default LLM provider
    path). Pass a custom callable to mock inference in tests, wrap with metrics,
    swap backends, or synthesize fallback verdicts on exception.

    Contract: ``async (*, construct: AICall[I, O], model_input: I) -> O``.
    Parameter names match ``invoke_ai_call`` so consumers can wrap it,
    unwrapping its ``AICallResult``:
    ``return (await invoke_ai_call(construct=construct, model_input=model_input)).output``.
    A custom executor returns ``O`` directly and contributes no token usage
    to the ``AI_CALL_COMPLETED`` event; only the default path reports usage.
    Must be async — inference is always I/O. The compiler enforces this at
    compile time and raises ``ConstructCompilationError`` for sync callables.
    """

    def child_specs(self) -> list[tuple[Construct, str]]:
        return []


AICall.model_rebuild()
