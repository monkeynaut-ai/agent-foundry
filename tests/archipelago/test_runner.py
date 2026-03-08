"""Tests for run_archipelago and run_dev_test with mocked graph and handler."""

from unittest.mock import MagicMock, patch

from archipelago.runner import run_archipelago, run_dev_test


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


class TestRunDevTest:
    @patch("archipelago.runner.docker_worker_handler")
    def test_given_dev_test_input_when_called_then_docker_worker_handler_invoked_with_worker_input(
        self, mock_handler
    ):
        mock_handler.return_value = {"worker_result": {"status": "completed"}}
        dev_test_input = {
            "repo_url": "https://github.com/org/repo",
            "repo_ref": "main",
            "feature_spec": {"title": "Add login"},
            "test_commands": ["pdm run pytest"],
        }

        run_dev_test(dev_test_input)

        mock_handler.assert_called_once()
        state = mock_handler.call_args[0][0]
        assert "worker_input" in state

    @patch("archipelago.runner.docker_worker_handler")
    def test_given_constraints_with_turn_timeout_when_called_then_constraints_preserved(
        self, mock_handler
    ):
        mock_handler.return_value = {"worker_result": {"status": "completed"}}
        dev_test_input = {
            "repo_ref": "main",
            "feature_spec": {"title": "Add login"},
            "test_commands": ["pdm run pytest"],
            "constraints": {"turn_timeout_seconds": 7200},
        }

        run_dev_test(dev_test_input)

        state = mock_handler.call_args[0][0]
        assert state["worker_input"]["constraints"]["turn_timeout_seconds"] == 7200

    @patch("archipelago.runner.docker_worker_handler")
    def test_given_no_constraints_key_when_called_then_worker_constraints_defaults_applied(
        self, mock_handler
    ):
        mock_handler.return_value = {"worker_result": {"status": "completed"}}
        dev_test_input = {
            "repo_ref": "main",
            "feature_spec": {"title": "Add login"},
            "test_commands": ["pdm run pytest"],
        }

        run_dev_test(dev_test_input)

        state = mock_handler.call_args[0][0]
        assert state["worker_input"]["constraints"]["timeout_seconds"] == 3600
        assert state["worker_input"]["constraints"]["skip_permissions"] is False
