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

import asyncio
import logging
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel

from agent_foundry.ai_models.inference import InferenceParameters, InferenceRequest
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.ai_models.resilience import DEFAULT_RETRY_POLICY
from agent_foundry.constructs.models import get_type_args
from agent_foundry.models.usage import TokenUsage

if TYPE_CHECKING:
    from agent_foundry.constructs.ai_call import AICall

logger = logging.getLogger(__name__)


def _fallback_chain(entry: ModelEntry) -> list[ModelEntry]:
    """Follow ``ModelEntry.fallback`` into a list, stopping at None or a cycle."""
    chain: list[ModelEntry] = []
    seen = {id(entry)}
    node = entry.fallback
    while node is not None and id(node) not in seen:
        chain.append(node)
        seen.add(id(node))
        node = node.fallback
    return chain


# Effort level applied when only the coarse ``thinking`` bool requests reasoning.
_DEFAULT_THINKING_EFFORT = "medium"


def _resolve_effort(parameters: InferenceParameters) -> str | None:
    """Resolve the reasoning effort to apply, or None for no reasoning.

    ``effort`` is the control; the legacy ``thinking`` bool maps to a default
    effort when ``effort`` is unset. ``"none"`` means explicitly no reasoning.
    """
    effort = (
        parameters.effort
        if parameters.effort is not None
        else (_DEFAULT_THINKING_EFFORT if parameters.thinking else None)
    )
    return None if effort == "none" else effort


def _effective_parameters(
    parameters: InferenceParameters,
    capabilities: ModelCapabilities,
    *,
    is_primary: bool,
) -> InferenceParameters:
    """Adjust call parameters to the target model's capabilities.

    - Reasoning (``effort``, or the ``thinking`` bool) on a model that doesn't
      support it is a misconfiguration: raise on the primary (loud, localized),
      but drop it on a fallback so failover still works.
    - ``max_tokens`` defaults to the model's ``max_output_tokens`` when unset
      and is clamped to it when over — never silently exceed the model's cap.

    The returned parameters carry the resolved reasoning level in ``effort``
    (``thinking`` normalized to None), so providers read a single field.
    """
    effort = _resolve_effort(parameters)
    if effort is not None and not capabilities.supports_thinking:
        if is_primary:
            raise ValueError(
                "AICall requested reasoning (effort/thinking) but the model does "
                "not support it (capabilities.supports_thinking is False)"
            )
        effort = None

    requested = parameters.max_tokens
    max_tokens = capabilities.max_output_tokens if requested is None else requested
    max_tokens = min(max_tokens, capabilities.max_output_tokens)

    return parameters.model_copy(
        update={"effort": effort, "thinking": None, "max_tokens": max_tokens}
    )


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
    primary = (
        construct.model if isinstance(construct.model, ModelEntry) else construct.model(model_input)
    )
    retry_policy = construct.retry or DEFAULT_RETRY_POLICY
    chain = construct.fallbacks if construct.fallbacks is not None else _fallback_chain(primary)
    candidates = [primary, *chain]

    # Outer loop: fail over down the chain. Inner loop: retry transient errors
    # against the current model. A persistent error (or exhausted retries)
    # advances to the next model; if all fail, the last error propagates.
    last_exc: Exception | None = None
    for entry in candidates:
        effective = _effective_parameters(
            parameters, entry.capabilities, is_primary=entry is primary
        )
        request = InferenceRequest(
            model_id=entry.model_id,
            instructions=instructions,
            prompt=prompt,
            parameters=effective,
            output_type=output_type,
        )
        for attempt in range(1, retry_policy.max_attempts + 1):
            try:
                result = await entry.provider(request)
                if not isinstance(result.output, output_type):
                    raise TypeError(
                        f"AICall provider returned {type(result.output).__name__}, "
                        f"expected {output_type.__name__}"
                    )
                return cast(
                    "AICallResult[O]",
                    AICallResult(output=result.output, usage=result.usage),
                )
            except Exception as exc:
                last_exc = exc
                if entry.provider.is_transient(exc) and attempt < retry_policy.max_attempts:
                    logger.warning(
                        "transient error from %s (attempt %d/%d): %s; retrying",
                        entry.model_id,
                        attempt,
                        retry_policy.max_attempts,
                        exc,
                    )
                    await asyncio.sleep(retry_policy.backoff_for(attempt))
                    continue
                if entry is not candidates[-1]:
                    logger.warning("model %s failed (%s); failing over", entry.model_id, exc)
                break

    assert last_exc is not None  # candidates is always non-empty (primary)
    raise last_exc
