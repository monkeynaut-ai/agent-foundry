"""Tests for the AI model registry and built-in Model entries."""

from __future__ import annotations

import pytest

from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry, get_model, register_model


class TestBuiltinModels:
    def test_claude_haiku_4_5_model_id(self):
        from agent_foundry.ai_models.model import Model

        assert Model.CLAUDE_HAIKU_4_5.model_id == "claude-haiku-4-5-20251001"

    def test_claude_sonnet_4_6_model_id(self):
        from agent_foundry.ai_models.model import Model

        assert Model.CLAUDE_SONNET_4_6.model_id == "claude-sonnet-4-6"

    def test_claude_opus_4_7_model_id(self):
        from agent_foundry.ai_models.model import Model

        assert Model.CLAUDE_OPUS_4_7.model_id == "claude-opus-4-7"

    def test_builtin_models_have_providers(self):
        from agent_foundry.ai_models.model import Model

        assert callable(Model.CLAUDE_HAIKU_4_5.provider)
        assert callable(Model.CLAUDE_SONNET_4_6.provider)
        assert callable(Model.CLAUDE_OPUS_4_7.provider)

    def test_builtin_models_retrievable_by_name(self):
        from agent_foundry.ai_models.model import Model

        assert get_model("CLAUDE_HAIKU_4_5") is Model.CLAUDE_HAIKU_4_5
        assert get_model("CLAUDE_SONNET_4_6") is Model.CLAUDE_SONNET_4_6
        assert get_model("CLAUDE_OPUS_4_7") is Model.CLAUDE_OPUS_4_7


class TestModelRegistry:
    def test_register_and_retrieve_custom_model(self):
        entry = ModelEntry(
            model_id="custom-model",
            provider=object(),
            capabilities=ModelCapabilities(context_window=8000, max_output_tokens=1000),
        )
        register_model("CUSTOM_TEST_MODEL", entry)
        assert get_model("CUSTOM_TEST_MODEL") is entry

    def test_register_duplicate_raises(self):
        entry = ModelEntry(
            model_id="dup-model",
            provider=object(),
            capabilities=ModelCapabilities(context_window=8000, max_output_tokens=1000),
        )
        register_model("DUP_TEST_MODEL", entry)
        with pytest.raises(ValueError, match="already registered"):
            register_model("DUP_TEST_MODEL", entry)

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError):
            get_model("DOES_NOT_EXIST_XYZ")
