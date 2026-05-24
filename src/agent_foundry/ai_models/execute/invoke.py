"""Direct execution of an ``AICall`` declaration.

Standalone invocation path — no compiler, no ``RunContext``, no
LangGraph. Resolves each callable-or-static field on the request,
builds an ``InferenceRequest``, calls the provider, and validates
output type. Both the compiler node and out-of-band callers (eval
harness, scripts, ad-hoc tooling) consume this function as the single
canonical implementation of "given an AICall + typed input, run it
and return typed output."
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pydantic import BaseModel

from agent_foundry.ai_models.inference import InferenceParameters, InferenceRequest
from agent_foundry.ai_models.model import ModelEntry
from agent_foundry.primitives.models import get_type_args

if TYPE_CHECKING:
    from agent_foundry.primitives.ai_call import AICall


async def invoke_ai_call[I: BaseModel, O: BaseModel](
    primitive: AICall[I, O],
    model_input: I,
) -> O:
    """Invoke ``primitive`` against ``model_input`` and return the typed output.

    Raises ``TypeError`` if the provider returns an object that isn't an
    instance of the request's declared output type.

    Parameter names match the AICall executor contract so consumers can
    wrap this function directly:
    ``return await invoke_ai_call(primitive=primitive, model_input=model_input)``.
    """
    _, output_type = get_type_args(primitive)

    instructions = (
        primitive.model_input.instructions
        if isinstance(primitive.model_input.instructions, str)
        else primitive.model_input.instructions(model_input)
    )
    prompt = (
        primitive.model_input.prompt
        if isinstance(primitive.model_input.prompt, str)
        else primitive.model_input.prompt(model_input)
    )
    parameters = (
        primitive.parameters
        if isinstance(primitive.parameters, InferenceParameters)
        else primitive.parameters(model_input)
    )
    model_entry = (
        primitive.model if isinstance(primitive.model, ModelEntry) else primitive.model(model_input)
    )

    request = InferenceRequest(
        model_id=model_entry.model_id,
        instructions=instructions,
        prompt=prompt,
        parameters=parameters,
        output_type=output_type,
    )
    result = await model_entry.provider(request)

    if not isinstance(result, output_type):
        raise TypeError(
            f"AICall provider returned {type(result).__name__}, expected {output_type.__name__}"
        )
    return cast("O", result)
