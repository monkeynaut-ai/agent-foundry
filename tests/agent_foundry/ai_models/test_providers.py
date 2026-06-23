"""AnthropicProvider client construction is lazy.

The provider must not capture ``ANTHROPIC_API_KEY`` at construction time —
products commonly call ``load_dotenv()`` after importing the module that
builds the provider, so the key is only present by the time the first
inference call runs.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from agent_foundry.ai_models.inference import InferenceParameters, InferenceRequest
from agent_foundry.ai_models.providers import AnthropicProvider, OpenAIProvider


def test_construction_does_not_build_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = AnthropicProvider()
    assert provider._client_instance is None


def test_key_set_after_construction_is_picked_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = AnthropicProvider()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-late")
    assert provider._client.api_key == "sk-test-late"


def test_explicit_key_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    provider = AnthropicProvider(api_key="sk-explicit")
    assert provider._client.api_key == "sk-explicit"


def test_client_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    provider = AnthropicProvider()
    assert provider._client is provider._client


@pytest.mark.asyncio
async def test_close_on_unused_provider_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = AnthropicProvider()
    await provider.close()
    assert provider._client_instance is None


# -- OpenAIProvider --


class _Answer(BaseModel):
    answer: str


def test_openai_construction_does_not_build_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIProvider()
    assert provider._client_instance is None


def test_openai_key_set_after_construction_is_picked_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIProvider()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-late")
    assert provider._client.api_key == "sk-late"


def test_openai_explicit_key_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    provider = OpenAIProvider(api_key="sk-explicit")
    assert provider._client.api_key == "sk-explicit"


@pytest.mark.asyncio
async def test_openai_call_maps_request_output_and_usage() -> None:
    provider = OpenAIProvider(api_key="x")
    fake_response = SimpleNamespace(
        output_parsed=_Answer(answer="Paris"),
        usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 3, "output_tokens": 5}),
    )
    parse_mock = AsyncMock(return_value=fake_response)
    provider._client_instance = SimpleNamespace(responses=SimpleNamespace(parse=parse_mock))

    request = InferenceRequest(
        model_id="gpt-5.4",
        instructions="Answer concisely.",
        prompt="Capital of France?",
        parameters=InferenceParameters(max_tokens=10),
        output_type=_Answer,
    )
    result = await provider(request)

    assert result.output == _Answer(answer="Paris")
    assert result.usage is not None
    assert result.usage.input_tokens == 3
    assert result.usage.output_tokens == 5

    kwargs = parse_mock.call_args.kwargs
    assert kwargs["model"] == "gpt-5.4"
    assert kwargs["instructions"] == "Answer concisely."
    assert kwargs["input"] == "Capital of France?"
    assert kwargs["text_format"] is _Answer
    assert kwargs["max_output_tokens"] == 10
    # temperature unset -> not forwarded (some reasoning models reject it)
    assert "temperature" not in kwargs


@pytest.mark.asyncio
async def test_openai_call_forwards_temperature_when_set() -> None:
    provider = OpenAIProvider(api_key="x")
    fake_response = SimpleNamespace(output_parsed=_Answer(answer="x"), usage=None)
    parse_mock = AsyncMock(return_value=fake_response)
    provider._client_instance = SimpleNamespace(responses=SimpleNamespace(parse=parse_mock))

    request = InferenceRequest(
        model_id="gpt-5.4",
        instructions="i",
        prompt="p",
        parameters=InferenceParameters(temperature=0.5),
        output_type=_Answer,
    )
    result = await provider(request)
    assert result.usage is None  # degrade gracefully when backend reports none
    assert parse_mock.call_args.kwargs["temperature"] == 0.5


@pytest.mark.asyncio
async def test_openai_close_on_unused_provider_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIProvider()
    await provider.close()
    assert provider._client_instance is None
