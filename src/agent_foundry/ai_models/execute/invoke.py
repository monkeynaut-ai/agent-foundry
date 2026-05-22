"""Direct execution of an ``AIRequest`` declaration.

Standalone invocation path — no compiler, no ``RunContext``, no
LangGraph. Resolves each callable-or-static field on the request,
builds an ``InferenceRequest``, calls the provider, and validates
output type. Both the compiler node and out-of-band callers (eval
harness, scripts, ad-hoc tooling) consume this function as the single
canonical implementation of "given an AIRequest + typed input, run it
and return typed output."
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pydantic import BaseModel

from agent_foundry.ai_models.inference import InferenceParameters, InferenceRequest
from agent_foundry.ai_models.model import ModelEntry
from agent_foundry.primitives.models import get_type_args

if TYPE_CHECKING:
    from agent_foundry.primitives.ai_request import AIRequest


async def invoke_ai_request[I: BaseModel, O: BaseModel](
    req: AIRequest[I, O],
    input_state: I,
) -> O:
    """Invoke ``req`` against ``input_state`` and return the typed output.

    Raises ``TypeError`` if the provider returns an object that isn't an
    instance of the request's declared output type.
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
        model_id=model_entry.model_id,
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
