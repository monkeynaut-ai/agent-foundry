"""AI model registry and built-in model entries."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from agent_foundry.ai_models.inference import InferenceProvider


class ModelCapabilities(BaseModel):
    """Capability metadata for an AI model."""

    context_window: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)
    supports_thinking: bool = False
    supports_vision: bool = False


@dataclass
class ModelEntry:
    """A registered AI model — its identity, provider, and capabilities."""

    model_id: str
    provider: InferenceProvider
    capabilities: ModelCapabilities


_registry: dict[str, ModelEntry] = {}


def register_model(name: str, entry: ModelEntry) -> None:
    """Register a model entry under the given name.

    Raises ``ValueError`` if the name is already registered.
    """
    if name in _registry:
        raise ValueError(f"Model already registered: {name!r}")
    _registry[name] = entry


def get_model(name: str) -> ModelEntry:
    """Return the registered model entry for the given name.

    Raises ``KeyError`` if no model is registered under that name.
    """
    if name not in _registry:
        raise KeyError(f"No model registered: {name!r}")
    return _registry[name]


class Model:
    """Built-in AI model entries."""

    CLAUDE_OPUS_4_7: ModelEntry
    CLAUDE_SONNET_4_6: ModelEntry
    CLAUDE_HAIKU_4_5: ModelEntry


def _register_builtins() -> None:
    from agent_foundry.ai_models.providers import AnthropicProvider

    # AsyncAnthropic is safe for concurrent use within an event loop.
    anthropic = AnthropicProvider()

    Model.CLAUDE_OPUS_4_7 = ModelEntry(
        model_id="claude-opus-4-7",
        provider=anthropic,
        capabilities=ModelCapabilities(
            context_window=200_000,
            max_output_tokens=32_000,
            supports_thinking=True,
            supports_vision=True,
        ),
    )
    register_model("CLAUDE_OPUS_4_7", Model.CLAUDE_OPUS_4_7)

    Model.CLAUDE_SONNET_4_6 = ModelEntry(
        model_id="claude-sonnet-4-6",
        provider=anthropic,
        capabilities=ModelCapabilities(
            context_window=200_000,
            max_output_tokens=64_000,
            supports_thinking=False,
            supports_vision=True,
        ),
    )
    register_model("CLAUDE_SONNET_4_6", Model.CLAUDE_SONNET_4_6)

    Model.CLAUDE_HAIKU_4_5 = ModelEntry(
        model_id="claude-haiku-4-5-20251001",
        provider=anthropic,
        capabilities=ModelCapabilities(
            context_window=200_000,
            max_output_tokens=8_192,
            supports_thinking=False,
            supports_vision=True,
        ),
    )
    register_model("CLAUDE_HAIKU_4_5", Model.CLAUDE_HAIKU_4_5)


_register_builtins()
