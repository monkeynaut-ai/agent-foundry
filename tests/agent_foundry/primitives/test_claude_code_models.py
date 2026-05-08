"""Tests for ClaudeModel enum and list_claude_models."""

from unittest.mock import MagicMock, patch


class TestClaudeModel:
    def test_members_are_strings(self):
        from agent_foundry.primitives import ClaudeModel

        for model in ClaudeModel:
            assert isinstance(model, str)

    def test_values_are_valid_claude_ids(self):
        from agent_foundry.primitives import ClaudeModel

        for model in ClaudeModel:
            assert model.startswith("claude-")

    def test_known_members_present(self):
        from agent_foundry.primitives import ClaudeModel

        assert ClaudeModel.OPUS_4_7 == "claude-opus-4-7"
        assert ClaudeModel.SONNET_4_6 == "claude-sonnet-4-6"
        assert ClaudeModel.HAIKU_4_5 == "claude-haiku-4-5-20251001"


class TestListClaudeModels:
    def test_returns_list_of_strings(self):
        from agent_foundry.primitives import list_claude_models

        mock_model = MagicMock()
        mock_model.id = "claude-sonnet-4-6"
        mock_page = MagicMock()
        mock_page.__iter__ = MagicMock(return_value=iter([mock_model]))

        with patch("agent_foundry.primitives.claude_code.anthropic.Anthropic") as mock_client_cls:
            mock_client_cls.return_value.models.list.return_value = mock_page
            result = list_claude_models()

        assert isinstance(result, list)
        assert result == ["claude-sonnet-4-6"]

    def test_returns_all_model_ids(self):
        from agent_foundry.primitives import list_claude_models

        ids = ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]
        mock_models = [MagicMock(id=i) for i in ids]
        mock_page = MagicMock()
        mock_page.__iter__ = MagicMock(return_value=iter(mock_models))

        with patch("agent_foundry.primitives.claude_code.anthropic.Anthropic") as mock_client_cls:
            mock_client_cls.return_value.models.list.return_value = mock_page
            result = list_claude_models()

        assert result == ids


class TestPublicAPI:
    def test_importable_from_primitives(self):
        from agent_foundry.primitives import ClaudeModel, list_claude_models

        assert ClaudeModel
        assert list_claude_models
