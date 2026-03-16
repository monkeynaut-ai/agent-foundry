"""ArchitectureHandler — unit tests for deterministic architecture handler."""

import pytest

from agent_foundry.registry.spec import load_role_spec
from archipelago.agents.architecture import ArchitectureHandler

from ..conftest import PRODUCT_ROLES_DIR


def _make_spec():
    return load_role_spec(PRODUCT_ROLES_DIR / "architecture_generate_feature_arch.yaml")


def _make_state():
    return {
        "product_brief": {
            "name": "Product: Build a task management app",
            "problem_statement": "Users need a solution for: Build a task management app",
            "target_personas": ["Developer", "Product Manager", "End User"],
            "success_metrics": [
                "User adoption rate",
                "Task completion time",
                "User satisfaction score",
            ],
            "constraints": ["Must integrate with existing systems", "Budget-conscious deployment"],
        },
    }


class TestArchitectureHandler:
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

    def test_given_missing_product_brief_when_called_then_raises_value_error(self):
        handler = ArchitectureHandler(_make_spec())
        with pytest.raises(ValueError, match="product_brief is required"):
            handler({})
