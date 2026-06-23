"""Public-API export guarantees for the AI provider/model seam.

A product adding a custom provider must be able to import the seam from the
package without reaching into internal modules; pin that surface here.
"""

import agent_foundry.ai_models as ai_models


def test_provider_seam_is_publicly_exported():
    from agent_foundry.ai_models import (
        InferenceParameters,
        InferenceProvider,
        InferenceRequest,
        InferenceResult,
        Model,
        ModelCapabilities,
        ModelEntry,
        get_model,
        register_model,
    )

    expected = {
        "InferenceParameters",
        "InferenceProvider",
        "InferenceRequest",
        "InferenceResult",
        "Model",
        "ModelCapabilities",
        "ModelEntry",
        "get_model",
        "register_model",
    }
    assert expected <= set(ai_models.__all__)
    # The seam a custom provider implements/uses resolves to the real symbols.
    assert ai_models.InferenceProvider is InferenceProvider
    assert ai_models.ModelEntry is ModelEntry
    assert callable(register_model)
    assert callable(get_model)
    assert InferenceParameters and InferenceRequest and InferenceResult
    assert Model and ModelCapabilities


def test_concrete_providers_are_publicly_exported():
    from agent_foundry.ai_models import AnthropicProvider, OpenAIProvider

    assert {"AnthropicProvider", "OpenAIProvider"} <= set(ai_models.__all__)
    assert ai_models.AnthropicProvider is AnthropicProvider
    assert ai_models.OpenAIProvider is OpenAIProvider


def test_openai_models_are_registered():
    from agent_foundry.ai_models import Model, get_model

    assert get_model("GPT_5_5") is Model.GPT_5_5
    assert get_model("GPT_5_4") is Model.GPT_5_4
    assert get_model("GPT_5_4_MINI") is Model.GPT_5_4_MINI
    assert Model.GPT_5_5.model_id == "gpt-5.5"
    assert Model.GPT_5_4.model_id == "gpt-5.4"
    assert Model.GPT_5_4_MINI.model_id == "gpt-5.4-mini"
    # Capabilities sourced from the OpenAI model docs.
    assert Model.GPT_5_5.capabilities.context_window == 1_050_000
    assert Model.GPT_5_4.capabilities.context_window == 1_050_000
    assert Model.GPT_5_4_MINI.capabilities.context_window == 400_000


def test_retry_policy_is_publicly_exported():
    from agent_foundry.ai_models import DEFAULT_RETRY_POLICY, RetryPolicy

    assert {"RetryPolicy", "DEFAULT_RETRY_POLICY"} <= set(ai_models.__all__)
    assert isinstance(DEFAULT_RETRY_POLICY, RetryPolicy)


def test_builtin_models_have_same_family_fallback_chains():
    from agent_foundry.ai_models import Model

    # Same-family default chains (cross-provider is opt-in via override).
    assert Model.GPT_5_5.fallback is Model.GPT_5_4
    assert Model.GPT_5_4.fallback is Model.GPT_5_4_MINI
    assert Model.GPT_5_4_MINI.fallback is None
    assert Model.CLAUDE_OPUS_4_7.fallback is Model.CLAUDE_SONNET_4_6
    assert Model.CLAUDE_SONNET_4_6.fallback is Model.CLAUDE_HAIKU_4_5
    assert Model.CLAUDE_HAIKU_4_5.fallback is None
