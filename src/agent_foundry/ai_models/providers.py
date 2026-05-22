"""Concrete inference provider implementations."""

from __future__ import annotations

import os

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from agent_foundry.ai_models.inference import InferenceProvider, InferenceRequest


class AnthropicProvider(InferenceProvider):
    """Inference provider backed by the Anthropic Messages API.

    A connection to Anthropic — owns one ``AsyncAnthropic`` client (and
    its connection pool) for the lifetime of the instance. ``AsyncAnthropic``
    is safe for concurrent use within an event loop.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._client = AsyncAnthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    async def __call__(self, request: InferenceRequest) -> BaseModel:
        tool = {
            "name": "structured_output",
            "description": "Return the structured response.",
            "input_schema": request.output_type.model_json_schema(),
        }
        kwargs: dict = {
            "model": request.model_id,
            "system": request.instructions,
            "messages": [{"role": "user", "content": request.prompt}],
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": "structured_output"},
            "max_tokens": request.parameters.max_tokens or 1024,
        }
        if request.parameters.temperature is not None:
            kwargs["temperature"] = request.parameters.temperature

        response = await self._client.messages.create(**kwargs)
        tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use_block is None:
            raise RuntimeError(
                f"Anthropic provider returned no tool_use block for model {request.model_id!r}"
            )
        return request.output_type.model_validate(tool_use_block.input)

    async def close(self) -> None:
        await self._client.close()
