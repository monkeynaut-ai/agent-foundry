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
    """A registered AI model — its identity, provider, and capabilities.

    ``fallback`` is the model to fail over to when this one persistently fails
    (after retries). Following ``fallback`` forms a chain; ``None`` ends it.
    """

    model_id: str
    provider: InferenceProvider
    capabilities: ModelCapabilities
    fallback: ModelEntry | None = None


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
    GPT_5_5: ModelEntry
    GPT_5_4: ModelEntry
    GPT_5_4_MINI: ModelEntry


def _register_builtins() -> None:
    from agent_foundry.ai_models.providers import AnthropicProvider, OpenAIProvider

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

    # OpenAI models call the same Anthropic-free path through OpenAIProvider.
    # Capability values per the OpenAI model docs (developers.openai.com).
    openai = OpenAIProvider()

    Model.GPT_5_5 = ModelEntry(
        model_id="gpt-5.5",
        provider=openai,
        capabilities=ModelCapabilities(
            context_window=1_050_000,
            max_output_tokens=128_000,
            supports_thinking=True,
            supports_vision=True,
        ),
    )
    register_model("GPT_5_5", Model.GPT_5_5)

    Model.GPT_5_4 = ModelEntry(
        model_id="gpt-5.4",
        provider=openai,
        capabilities=ModelCapabilities(
            context_window=1_050_000,
            max_output_tokens=128_000,
            supports_thinking=True,
            supports_vision=True,
        ),
    )
    register_model("GPT_5_4", Model.GPT_5_4)

    Model.GPT_5_4_MINI = ModelEntry(
        model_id="gpt-5.4-mini",
        provider=openai,
        capabilities=ModelCapabilities(
            context_window=400_000,
            max_output_tokens=128_000,
            supports_thinking=True,
            supports_vision=True,
        ),
    )
    register_model("GPT_5_4_MINI", Model.GPT_5_4_MINI)

    # Default failover chains — same family (least surprising). Cross-provider
    # redundancy is available to products by overriding fallback or passing an
    # AICall.fallbacks chain.
    Model.CLAUDE_OPUS_4_7.fallback = Model.CLAUDE_SONNET_4_6
    Model.CLAUDE_SONNET_4_6.fallback = Model.CLAUDE_HAIKU_4_5
    Model.GPT_5_5.fallback = Model.GPT_5_4
    Model.GPT_5_4.fallback = Model.GPT_5_4_MINI


_register_builtins()
