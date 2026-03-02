"""CLI behavior tests for the Decision Support demo."""

import json
from unittest.mock import patch

import pytest

from agent_foundry.demo import cli


def _sample_result(gate_failure: str | None = None) -> dict:
    result = {
        "question": "What should we do?",
        "domain": "general",
        "recommendation": {
            "recommendation": "Prioritize option A",
            "assumptions": ["A1"],
            "uncertainty": {"confidence": 0.8, "rationale": "Strong evidence"},
        },
        "retrieved_evidence": [{"id": "e1", "text": "Evidence 1"}],
        "schema_valid": True,
        "citations_valid": True,
        "uncertainty_valid": True,
        "evidence_valid": True,
    }
    if gate_failure is not None:
        result["gate_failure"] = gate_failure
    return result


def test_cli_json_output(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["agent-foundry-demo", "What should we do?", "--json"])
    with patch("agent_foundry.demo.cli.run_demo", return_value=_sample_result()) as run_demo_mock:
        cli.main()

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["question"] == "What should we do?"
    run_demo_mock.assert_called_once_with("What should we do?", domain="general", constraints=[])


def test_cli_human_readable_output(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["agent-foundry-demo", "What should we do?"])
    with patch("agent_foundry.demo.cli.run_demo", return_value=_sample_result()):
        cli.main()

    out = capsys.readouterr().out
    assert "Question: What should we do?" in out
    assert "Recommendation: Prioritize option A" in out
    assert "schema_valid: PASS" in out
    assert "[e1] Evidence 1" in out


def test_cli_gate_failure_exits_nonzero(monkeypatch):
    monkeypatch.setattr("sys.argv", ["agent-foundry-demo", "What should we do?"])
    with (
        patch(
            "agent_foundry.demo.cli.run_demo", return_value=_sample_result(gate_failure="schema")
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        cli.main()
    assert exc_info.value.code == 1
