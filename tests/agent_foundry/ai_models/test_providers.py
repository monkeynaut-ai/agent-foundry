"""AnthropicProvider client construction is lazy.

The provider must not capture ``ANTHROPIC_API_KEY`` at construction time —
products commonly call ``load_dotenv()`` after importing the module that
builds the provider, so the key is only present by the time the first
inference call runs.
"""

from __future__ import annotations

import pytest

from agent_foundry.ai_models.providers import AnthropicProvider


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
