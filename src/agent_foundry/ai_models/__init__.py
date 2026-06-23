"""AI model inference: the provider seam, model registry, and built-in models.

Public surface for making direct LLM calls (via ``AICall``) and for adding a
custom provider: implement :class:`InferenceProvider`, register a
:class:`ModelEntry` with :func:`register_model`, and reference it from an
``AICall``.
"""

from agent_foundry.ai_models.inference import (
    InferenceParameters,
    InferenceProvider,
    InferenceRequest,
    InferenceResult,
)
from agent_foundry.ai_models.model import (
    Model,
    ModelCapabilities,
    ModelEntry,
    get_model,
    register_model,
)
from agent_foundry.ai_models.providers import AnthropicProvider, OpenAIProvider

__all__ = [
    "AnthropicProvider",
    "InferenceParameters",
    "InferenceProvider",
    "InferenceRequest",
    "InferenceResult",
    "Model",
    "ModelCapabilities",
    "ModelEntry",
    "OpenAIProvider",
    "get_model",
    "register_model",
]
