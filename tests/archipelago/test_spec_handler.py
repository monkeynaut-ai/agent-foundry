"""SpecHandler — unit tests for deterministic spec handler."""

from pathlib import Path

import pytest

from agent_foundry.registry.spec import load_capability_spec
from archipelago.agents.spec import SpecHandler

CAPABILITIES_DIR = Path(__file__).parent.parent.parent / "capabilities"


def _make_spec():
    return load_capability_spec(CAPABILITIES_DIR / "spec_generate_feature_spec.yaml")


def _make_state():
    return {
        "feature_architecture": {
            "feature_name": "Task Manager Core",
            "components": ["API Gateway", "Task Service", "Database Layer"],
            "data_flow": "Client -> API Gateway -> Task Service -> Database",
            "technology_choices": ["Python", "FastAPI", "PostgreSQL"],
            "risks": ["Schema migration complexity"],
        },
    }


class TestSpecHandler:
    def test_given_spec_handler_when_instantiated_with_spec_then_stores_spec(self):
        spec = _make_spec()
        handler = SpecHandler(spec)
        assert handler.spec is spec

    def test_given_feature_architecture_when_called_then_returns_state_with_feature_spec(self):
        handler = SpecHandler(_make_spec())
        result = handler(_make_state())
        assert "feature_spec" in result
        assert isinstance(result["feature_spec"], dict)

    def test_given_feature_architecture_when_called_then_returns_state_with_test_plan(self):
        handler = SpecHandler(_make_spec())
        result = handler(_make_state())
        assert "test_plan" in result
        assert isinstance(result["test_plan"], dict)

    def test_given_feature_architecture_when_called_then_feature_spec_has_required_fields(self):
        handler = SpecHandler(_make_spec())
        result = handler(_make_state())
        fs = result["feature_spec"]
        assert "title" in fs
        assert "objective" in fs
        assert "acceptance_criteria" in fs
        assert "pr_slices" in fs
        assert isinstance(fs["acceptance_criteria"], list)
        assert isinstance(fs["pr_slices"], list)

    def test_given_feature_architecture_when_called_then_test_plan_has_required_fields(self):
        handler = SpecHandler(_make_spec())
        result = handler(_make_state())
        tp = result["test_plan"]
        assert "feature_name" in tp
        assert "test_cases" in tp
        assert "coverage_targets" in tp

    def test_given_same_input_when_called_twice_then_returns_identical_output(self):
        handler = SpecHandler(_make_spec())
        state = _make_state()
        result1 = handler(state)
        result2 = handler(state)
        assert result1["feature_spec"] == result2["feature_spec"]
        assert result1["test_plan"] == result2["test_plan"]

    def test_given_missing_feature_architecture_when_called_then_raises_value_error(self):
        handler = SpecHandler(_make_spec())
        with pytest.raises(ValueError, match="feature_architecture is required"):
            handler({})

    def test_given_feature_architecture_when_called_then_prints_input_and_output_to_stdout(self, capsys):
        handler = SpecHandler(_make_spec())
        handler(_make_state())
        captured = capsys.readouterr()
        assert "[spec] Input:" in captured.out
        assert "[spec] Generated feature spec:" in captured.out
