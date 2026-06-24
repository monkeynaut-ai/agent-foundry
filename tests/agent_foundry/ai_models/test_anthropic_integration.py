"""Integration smoke test for AnthropicProvider against the real API.

Proves structured output round-trips, and that adaptive thinking + effort is
compatible with the forced structured-output tool_choice (verified the API
constraint differs from the legacy enabled-thinking shape). Skips when
``ANTHROPIC_API_KEY`` is absent.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pydantic import BaseModel

from agent_foundry.ai_models.inference import InferenceParameters, InferenceRequest
from agent_foundry.ai_models.providers import AnthropicProvider

_REPO_ROOT = Path(__file__).resolve().parents[3]
# Read the key from .env explicitly rather than via load_dotenv: the session
# conftest strips ANTHROPIC_API_KEY from os.environ so `claude -p` subprocesses
# can't bill against it. This in-process provider call spawns no subprocess, so
# passing the key directly is safe and doesn't repopulate the environment.
_ANTHROPIC_KEY = dotenv_values(_REPO_ROOT / ".env").get("ANTHROPIC_API_KEY")
_MODEL = os.environ.get("ANTHROPIC_TEST_MODEL", "claude-opus-4-7")


class _Capital(BaseModel):
    city: str


@pytest.mark.integration
@pytest.mark.asyncio
async def test_anthropic_provider_returns_structured_output() -> None:
    if not _ANTHROPIC_KEY:
        pytest.skip("ANTHROPIC_API_KEY not in .env")

    provider = AnthropicProvider(api_key=_ANTHROPIC_KEY)
    request = InferenceRequest(
        model_id=_MODEL,
        instructions="Answer with only the city name.",
        prompt="What is the capital of France?",
        parameters=InferenceParameters(max_tokens=2048),
        output_type=_Capital,
    )
    try:
        result = await provider(request)
    finally:
        await provider.close()

    assert isinstance(result.output, _Capital)
    assert result.output.city.strip()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_anthropic_provider_with_reasoning_effort() -> None:
    if not _ANTHROPIC_KEY:
        pytest.skip("ANTHROPIC_API_KEY not in .env")

    provider = AnthropicProvider(api_key=_ANTHROPIC_KEY)
    request = InferenceRequest(
        model_id=_MODEL,
        instructions="Answer with only the city name.",
        prompt="What is the capital of France?",
        parameters=InferenceParameters(effort="low", max_tokens=2048),
        output_type=_Capital,
    )
    try:
        result = await provider(request)
    finally:
        await provider.close()

    # adaptive thinking + effort coexists with the forced structured-output tool.
    assert isinstance(result.output, _Capital)
    assert result.output.city.strip()
