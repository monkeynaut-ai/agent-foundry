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
