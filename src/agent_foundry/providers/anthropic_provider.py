"""Anthropic provider adapter for AIRequest."""

from __future__ import annotations

import os
from typing import Any

import anthropic
from pydantic import BaseModel

from agent_foundry.primitives.ai_request import ModelConfiguration


async def call_anthropic(
    instructions: str,
    prompt: str,
    config: ModelConfiguration,
    output_type: type[BaseModel],
) -> BaseModel:
    """Make a single Anthropic inference call and return a validated output_type instance.

    Uses tool use to enforce structured output — the model is forced to call a
    single tool whose input schema matches output_type, eliminating the need for
    JSON extraction or code fence stripping.

    Reads ANTHROPIC_API_KEY from the environment.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")

    client = anthropic.AsyncAnthropic(api_key=api_key)

    tool: dict[str, Any] = {
        "name": "structured_output",
        "description": "Return the structured response.",
        "input_schema": output_type.model_json_schema(),
    }

    kwargs: dict[str, Any] = {
        "model": config.model,
        "system": instructions,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": "structured_output"},
        "max_tokens": config.max_tokens or 1024,
    }
    if config.temperature is not None:
        kwargs["temperature"] = config.temperature

    response = await client.messages.create(**kwargs)

    tool_use_block = next(
        (block for block in response.content if block.type == "tool_use"),
        None,
    )
    if tool_use_block is None:
        raise RuntimeError(
            f"Anthropic response contained no tool_use block; "
            f"stop_reason={response.stop_reason!r}, content={response.content!r}"
        )

    return output_type.model_validate(tool_use_block.input)
