"""Concrete inference provider implementations."""

from __future__ import annotations

import os

from anthropic import AsyncAnthropic

from agent_foundry.ai_models.inference import (
    InferenceProvider,
    InferenceRequest,
    InferenceResult,
)
from agent_foundry.models.usage import TokenUsage


class AnthropicProvider(InferenceProvider):
    """Inference provider backed by the Anthropic Messages API.

    A connection to Anthropic — owns one ``AsyncAnthropic`` client (and
    its connection pool) for the lifetime of the instance. ``AsyncAnthropic``
    is safe for concurrent use within an event loop.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key
        self._client_instance: AsyncAnthropic | None = None

    @property
    def _client(self) -> AsyncAnthropic:
        # Built on first use, not at construction, so a key loaded after this
        # provider is instantiated (the common load_dotenv()-after-import case)
        # is still picked up. No await between the None-check and the assignment,
        # so concurrent __call__s on the shared instance can't double-build.
        if self._client_instance is None:
            self._client_instance = AsyncAnthropic(
                api_key=self._api_key or os.environ.get("ANTHROPIC_API_KEY")
            )
        return self._client_instance

    async def __call__(self, request: InferenceRequest) -> InferenceResult:
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
        output = request.output_type.model_validate(tool_use_block.input)
        usage = TokenUsage.from_mapping(
            response.usage.model_dump() if response.usage is not None else None
        )
        return InferenceResult(output=output, usage=usage)

    async def close(self) -> None:
        # Read the backing field, not the property — closing must not lazily
        # build a client just to tear it down.
        if self._client_instance is not None:
            await self._client_instance.close()
