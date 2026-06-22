"""Direct execution of an ``AICall`` declaration.

Standalone invocation path — no compiler, no ``RunContext``, no
LangGraph. Resolves each callable-or-static field on the request,
builds an ``InferenceRequest``, calls the provider, and validates
output type. Both the compiler node and out-of-band callers (eval
harness, scripts, ad-hoc tooling) consume this function as the single
canonical implementation of "given an AICall + typed input, run it
and return typed output plus token usage."

Returns an ``AICallResult[O]`` carrying both the typed output and the
provider-reported :class:`TokenUsage`. Callers that only need the
output read ``.output``; the compiler additionally records ``.usage``
onto the ``AI_CALL_COMPLETED`` lifecycle event.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pydantic import BaseModel

from agent_foundry.ai_models.inference import InferenceParameters, InferenceRequest
from agent_foundry.ai_models.model import ModelEntry
from agent_foundry.constructs.models import get_type_args
from agent_foundry.models.usage import TokenUsage

if TYPE_CHECKING:
    from agent_foundry.constructs.ai_call import AICall


class AICallResult[O: BaseModel](BaseModel):
    """Typed output of an ``invoke_ai_call`` plus the call's token usage.

    ``usage`` is ``None`` when the provider reported no usable counts.
    No USD figure: the AICall path records tokens only.
    """

    output: O
    usage: TokenUsage | None = None


async def invoke_ai_call[I: BaseModel, O: BaseModel](
    construct: AICall[I, O],
    model_input: I,
) -> AICallResult[O]:
    """Invoke ``construct`` against ``model_input``; return output + usage.

    Raises ``TypeError`` if the provider returns an object that isn't an
    instance of the request's declared output type.

    Parameter names match the AICall executor contract so consumers can
    wrap this function directly:
    ``return await invoke_ai_call(construct=construct, model_input=model_input)``.
    """
    _, output_type = get_type_args(construct)

    instructions = (
        construct.model_input.instructions
        if isinstance(construct.model_input.instructions, str)
        else construct.model_input.instructions(model_input)
    )
    prompt = (
        construct.model_input.prompt
        if isinstance(construct.model_input.prompt, str)
        else construct.model_input.prompt(model_input)
    )
    parameters = (
        construct.parameters
        if isinstance(construct.parameters, InferenceParameters)
        else construct.parameters(model_input)
    )
    model_entry = (
        construct.model if isinstance(construct.model, ModelEntry) else construct.model(model_input)
    )

    request = InferenceRequest(
        model_id=model_entry.model_id,
        instructions=instructions,
        prompt=prompt,
        parameters=parameters,
        output_type=output_type,
    )
    result = await model_entry.provider(request)

    if not isinstance(result.output, output_type):
        raise TypeError(
            f"AICall provider returned {type(result.output).__name__}, "
            f"expected {output_type.__name__}"
        )
    return cast(
        "AICallResult[O]",
        AICallResult(output=result.output, usage=result.usage),
    )
