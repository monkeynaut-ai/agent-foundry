"""Archipelago CLI — unit tests."""

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


class TestCLI:
    def test_given_valid_yaml_file_when_cli_invoked_then_runs_pipeline(self, tmp_path):
        input_file = tmp_path / "input.yaml"
        input_file.write_text(yaml.dump({"product_brief_input": "Build a task management app"}))

        fake_result = {"product_brief_input": "Build a task management app", "product_brief": {"name": "Test"}}

        with patch("archipelago.cli.run_archipelago", return_value=fake_result) as mock_run:
            from archipelago.cli import main

            exit_code = main(["-f", str(input_file)])

        mock_run.assert_called_once_with("Build a task management app")
        assert exit_code == 0

    def test_given_missing_file_when_cli_invoked_then_exits_with_error(self, capsys):
        from archipelago.cli import main

        exit_code = main(["-f", "/nonexistent/path/input.yaml"])

        captured = capsys.readouterr()
        assert exit_code == 1
        assert "not found" in captured.err.lower() or "error" in captured.err.lower()

    def test_given_yaml_without_product_brief_input_when_cli_invoked_then_exits_with_error(
        self, tmp_path, capsys
    ):
        input_file = tmp_path / "input.yaml"
        input_file.write_text(yaml.dump({"other_field": "value"}))

        from archipelago.cli import main

        exit_code = main(["-f", str(input_file)])

        captured = capsys.readouterr()
        assert exit_code == 1
        assert "product_brief_input" in captured.err
