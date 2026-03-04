"""Tests for run_archipelago with mocked compile_plan and graph."""

from unittest.mock import MagicMock, patch

from archipelago.runner import run_archipelago


class TestRunArchipelago:
    @patch("archipelago.runner.compile_plan")
    @patch("archipelago.runner.load_archipelago_plan")
    def test_given_valid_input_when_called_then_invokes_graph_with_correct_state(
        self, mock_load_plan, mock_compile
    ):
        mock_plan = MagicMock()
        mock_load_plan.return_value = mock_plan

        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {"product_brief": {"name": "Test"}}
        mock_compile.return_value = mock_graph

        result = run_archipelago("Build a test app")

        mock_graph.invoke.assert_called_once_with({"product_brief_input": "Build a test app"})
        assert result == {"product_brief": {"name": "Test"}}
