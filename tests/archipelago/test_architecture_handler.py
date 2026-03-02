"""ArchitectureHandler — unit tests for deterministic architecture handler."""

from pathlib import Path

import pytest

from agent_foundry.registry.spec import load_capability_spec
from archipelago.agents.architecture import ArchitectureHandler

CAPABILITIES_DIR = Path(__file__).parent.parent.parent / "capabilities"


def _make_spec():
    return load_capability_spec(CAPABILITIES_DIR / "architecture_generate_feature_arch.yaml")


def _make_state():
    return {
        "product_brief": {
            "name": "Product: Build a task management app",
            "problem_statement": "Users need a solution for: Build a task management app",
            "target_personas": ["Developer", "Product Manager", "End User"],
            "success_metrics": ["User adoption rate", "Task completion time", "User satisfaction score"],
            "constraints": ["Must integrate with existing systems", "Budget-conscious deployment"],
        },
    }


class TestArchitectureHandler:
    def test_given_architecture_handler_when_instantiated_with_spec_then_stores_spec(self):
        spec = _make_spec()
        handler = ArchitectureHandler(spec)
        assert handler.spec is spec

    def test_given_product_brief_when_called_then_returns_state_with_feature_architecture(self):
        handler = ArchitectureHandler(_make_spec())
        result = handler(_make_state())
        assert "feature_architecture" in result
        assert isinstance(result["feature_architecture"], dict)

    def test_given_product_brief_when_called_then_feature_architecture_has_required_fields(self):
        handler = ArchitectureHandler(_make_spec())
        result = handler(_make_state())
        arch = result["feature_architecture"]
        assert "feature_name" in arch
        assert "components" in arch
        assert "data_flow" in arch
        assert "technology_choices" in arch
        assert isinstance(arch["components"], list)
        assert isinstance(arch["technology_choices"], list)

    def test_given_same_input_when_called_twice_then_returns_identical_output(self):
        handler = ArchitectureHandler(_make_spec())
        state = _make_state()
        result1 = handler(state)
        result2 = handler(state)
        assert result1["feature_architecture"] == result2["feature_architecture"]

    def test_given_missing_product_brief_when_called_then_raises_value_error(self):
        handler = ArchitectureHandler(_make_spec())
        with pytest.raises(ValueError, match="product_brief is required"):
            handler({})

    def test_given_product_brief_when_called_then_prints_input_and_output_to_stdout(self, capsys):
        handler = ArchitectureHandler(_make_spec())
        handler(_make_state())
        captured = capsys.readouterr()
        assert "[architecture] Input:" in captured.out
        assert "[architecture] Generated feature architecture:" in captured.out
