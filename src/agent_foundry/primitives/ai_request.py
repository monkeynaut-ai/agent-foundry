"""AIRequest primitive — single LLM inference call with structured output."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from pydantic import BaseModel, Field

from agent_foundry.ai_models.inference import InferenceParameters, InferenceRequest
from agent_foundry.ai_models.model import ModelEntry
from agent_foundry.primitives.models import Primitive, get_type_args


class ModelInput[I: BaseModel](BaseModel):
    """What the model reads: instructions (system prompt) and prompt (user message)."""

    instructions: str | Callable[[I], str]
    prompt: str | Callable[[I], str]


class AIRequest[I: BaseModel, O: BaseModel](Primitive[I, O], arbitrary_types_allowed=True):
    """Make a single LLM inference call and return structured output.

    A leaf primitive — no children, no tool loop. Returns an instance of O
    parsed from the model response.
    """

    model_input: ModelInput[I]
    model: ModelEntry | Callable[[I], ModelEntry]
    parameters: InferenceParameters | Callable[[I], InferenceParameters]
    timeout_seconds: int = Field(default=30, ge=1)


AIRequest.model_rebuild()


async def invoke_ai_request[I: BaseModel, O: BaseModel](
    req: AIRequest[I, O],
    input_state: I,
) -> O:
    """Invoke ``req`` against ``input_state`` and return the typed output.

    Resolves each callable-or-static field against the input, builds an
    ``InferenceRequest``, calls the model's provider, and validates the
    provider returned an instance of the primitive's declared output type.

    Direct invocation — no compiler, no ``RunContext``, no LangGraph.
    Callers that want telemetry/lifecycle/state-merging should go through
    the compiler (which itself delegates here for the resolve+invoke step).
    """
    _, output_type = get_type_args(req)

    instructions = (
        req.model_input.instructions
        if isinstance(req.model_input.instructions, str)
        else req.model_input.instructions(input_state)
    )
    prompt = (
        req.model_input.prompt
        if isinstance(req.model_input.prompt, str)
        else req.model_input.prompt(input_state)
    )
    parameters = (
        req.parameters
        if isinstance(req.parameters, InferenceParameters)
        else req.parameters(input_state)
    )
    model_entry = req.model if isinstance(req.model, ModelEntry) else req.model(input_state)

    request = InferenceRequest(
        instructions=instructions,
        prompt=prompt,
        parameters=parameters,
        output_type=output_type,
    )
    result = await model_entry.provider(request)

    if not isinstance(result, output_type):
        raise TypeError(
            f"AIRequest provider returned {type(result).__name__}, expected {output_type.__name__}"
        )
    return cast("O", result)
