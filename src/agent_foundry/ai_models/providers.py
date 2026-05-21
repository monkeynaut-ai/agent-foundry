"""Concrete inference provider implementations."""

from __future__ import annotations

import os

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from agent_foundry.ai_models.inference import InferenceProvider, InferenceRequest


def anthropic(model_id: str) -> InferenceProvider:
    """Return an InferenceProvider that calls the Anthropic API with the given model."""

    async def _call(request: InferenceRequest) -> BaseModel:
        client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        tool = {
            "name": "structured_output",
            "description": "Return the structured response.",
            "input_schema": request.output_type.model_json_schema(),
        }
        kwargs: dict = {
            "model": model_id,
            "system": request.instructions,
            "messages": [{"role": "user", "content": request.prompt}],
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": "structured_output"},
            "max_tokens": request.parameters.max_tokens or 1024,
        }
        if request.parameters.temperature is not None:
            kwargs["temperature"] = request.parameters.temperature

        response = await client.messages.create(**kwargs)
        tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use_block is None:
            raise RuntimeError(
                f"Anthropic provider returned no tool_use block for model {model_id!r}"
            )
        return request.output_type.model_validate(tool_use_block.input)

    return _call
