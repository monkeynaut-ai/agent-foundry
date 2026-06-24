"""AnthropicProvider client construction is lazy.

The provider must not capture ``ANTHROPIC_API_KEY`` at construction time —
products commonly call ``load_dotenv()`` after importing the module that
builds the provider, so the key is only present by the time the first
inference call runs.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import anthropic
import openai
import pytest
from pydantic import BaseModel, ValidationError

from agent_foundry.ai_models.inference import (
    InferenceParameters,
    InferenceRequest,
    ReasoningEffort,
)
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


def _openai_with_parse_mock():
    provider = OpenAIProvider(api_key="x")
    parse_mock = AsyncMock(
        return_value=SimpleNamespace(output_parsed=_Answer(answer="x"), usage=None)
    )
    provider._client_instance = SimpleNamespace(responses=SimpleNamespace(parse=parse_mock))
    return provider, parse_mock


@pytest.mark.asyncio
async def test_openai_forwards_reasoning_effort_when_set() -> None:
    provider, parse_mock = _openai_with_parse_mock()
    request = InferenceRequest(
        model_id="gpt-5.4",
        instructions="i",
        prompt="p",
        parameters=InferenceParameters(effort="high"),
        output_type=_Answer,
    )
    await provider(request)
    assert parse_mock.call_args.kwargs["reasoning"] == {"effort": "high"}


@pytest.mark.asyncio
async def test_openai_omits_reasoning_when_effort_unset() -> None:
    provider, parse_mock = _openai_with_parse_mock()
    request = InferenceRequest(
        model_id="gpt-5.4",
        instructions="i",
        prompt="p",
        parameters=InferenceParameters(),
        output_type=_Answer,
    )
    await provider(request)
    assert "reasoning" not in parse_mock.call_args.kwargs


@pytest.mark.asyncio
async def test_anthropic_forwards_adaptive_thinking_and_effort_when_set() -> None:
    provider = AnthropicProvider(api_key="x")
    block = SimpleNamespace(type="tool_use", input={"answer": "hi"})
    create_mock = AsyncMock(return_value=SimpleNamespace(content=[block], usage=None))
    provider._client_instance = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    request = InferenceRequest(
        model_id="claude-opus-4-7",
        instructions="i",
        prompt="p",
        parameters=InferenceParameters(effort="low"),
        output_type=_Answer,
    )
    result = await provider(request)
    assert result.output == _Answer(answer="hi")

    kwargs = create_mock.call_args.kwargs
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "low"}
    # Forced structured-output tool_choice is preserved (compatible with adaptive).
    assert kwargs["tool_choice"] == {"type": "tool", "name": "structured_output"}


@pytest.mark.asyncio
async def test_openai_forwards_minimal_effort_unchanged() -> None:
    provider, parse_mock = _openai_with_parse_mock()
    request = InferenceRequest(
        model_id="gpt-5.4",
        instructions="i",
        prompt="p",
        parameters=InferenceParameters(effort=ReasoningEffort.MINIMAL),
        output_type=_Answer,
    )
    await provider(request)
    # OpenAI supports 'minimal'; pass it through.
    assert parse_mock.call_args.kwargs["reasoning"] == {"effort": "minimal"}


@pytest.mark.asyncio
async def test_anthropic_maps_minimal_effort_to_low() -> None:
    provider = AnthropicProvider(api_key="x")
    block = SimpleNamespace(type="tool_use", input={"answer": "hi"})
    create_mock = AsyncMock(return_value=SimpleNamespace(content=[block], usage=None))
    provider._client_instance = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    request = InferenceRequest(
        model_id="claude-opus-4-7",
        instructions="i",
        prompt="p",
        parameters=InferenceParameters(effort=ReasoningEffort.MINIMAL),
        output_type=_Answer,
    )
    await provider(request)
    # Anthropic has no 'minimal' — normalized to 'low' so cross-provider failover works.
    assert create_mock.call_args.kwargs["output_config"] == {"effort": "low"}


def test_invalid_effort_rejected_at_construction() -> None:
    with pytest.raises(ValidationError):
        InferenceParameters(effort="extreme")


@pytest.mark.asyncio
async def test_anthropic_omits_reasoning_when_effort_unset() -> None:
    provider = AnthropicProvider(api_key="x")
    block = SimpleNamespace(type="tool_use", input={"answer": "hi"})
    create_mock = AsyncMock(return_value=SimpleNamespace(content=[block], usage=None))
    provider._client_instance = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    request = InferenceRequest(
        model_id="claude-opus-4-7",
        instructions="i",
        prompt="p",
        parameters=InferenceParameters(),
        output_type=_Answer,
    )
    await provider(request)
    kwargs = create_mock.call_args.kwargs
    assert "thinking" not in kwargs
    assert "output_config" not in kwargs


@pytest.mark.asyncio
async def test_openai_close_on_unused_provider_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIProvider()
    await provider.close()
    assert provider._client_instance is None


# -- is_transient classification --


def _status_error(sdk_cls, status: int):
    err = Mock(spec=sdk_cls)
    err.status_code = status
    return err


def test_openai_is_transient_classification() -> None:
    p = OpenAIProvider(api_key="x")
    assert p.is_transient(Mock(spec=openai.RateLimitError)) is True
    assert p.is_transient(Mock(spec=openai.APITimeoutError)) is True
    assert p.is_transient(Mock(spec=openai.APIConnectionError)) is True
    assert p.is_transient(Mock(spec=openai.InternalServerError)) is True
    assert p.is_transient(_status_error(openai.APIStatusError, 503)) is True
    assert p.is_transient(_status_error(openai.AuthenticationError, 401)) is False
    assert p.is_transient(_status_error(openai.BadRequestError, 400)) is False
    assert p.is_transient(ValueError("not an SDK error")) is False


def test_anthropic_is_transient_classification() -> None:
    p = AnthropicProvider(api_key="x")
    assert p.is_transient(Mock(spec=anthropic.RateLimitError)) is True
    assert p.is_transient(Mock(spec=anthropic.InternalServerError)) is True
    assert p.is_transient(_status_error(anthropic.APIStatusError, 502)) is True
    assert p.is_transient(_status_error(anthropic.AuthenticationError, 401)) is False
    assert p.is_transient(ValueError("not an SDK error")) is False
