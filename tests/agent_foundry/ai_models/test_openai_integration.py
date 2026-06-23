"""Integration smoke test for OpenAIProvider against the real API.

Proves native structured output round-trips end to end: a real
``responses.parse`` call returns an instance of the requested output model.
Skips when ``OPENAI_API_KEY`` is absent.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pydantic import BaseModel

from agent_foundry.ai_models.inference import InferenceParameters, InferenceRequest
from agent_foundry.ai_models.providers import OpenAIProvider

_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


class _Capital(BaseModel):
    city: str


@pytest.mark.integration
@pytest.mark.asyncio
async def test_openai_provider_returns_structured_output() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")

    provider = OpenAIProvider()
    request = InferenceRequest(
        model_id="gpt-5.4-mini",
        instructions="Answer with only the city name.",
        prompt="What is the capital of France?",
        parameters=InferenceParameters(),
        output_type=_Capital,
    )
    try:
        result = await provider(request)
    finally:
        await provider.close()

    assert isinstance(result.output, _Capital)
    assert result.output.city.strip()  # non-empty structured field
