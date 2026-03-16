"""StrategyHandler — unit tests for deterministic strategy handler."""

import pytest

from agent_foundry.registry.spec import RoleSpec, load_role_spec
from archipelago.agents.strategy import StrategyHandler

from ..conftest import PRODUCT_ROLES_DIR


def _make_spec() -> RoleSpec:
    return load_role_spec(PRODUCT_ROLES_DIR / "strategy_generate_product_brief.yaml")


class TestStrategyHandler:
    def test_given_product_brief_input_when_called_then_returns_state_with_product_brief(self):
        handler = StrategyHandler(_make_spec())
        state = {"product_brief_input": "Build a task management app"}
        result = handler(state)
        assert "product_brief" in result
        assert isinstance(result["product_brief"], dict)

    def test_given_product_brief_input_when_called_then_product_brief_has_required_fields(self):
        handler = StrategyHandler(_make_spec())
        state = {"product_brief_input": "Build a task management app"}
        result = handler(state)
        brief = result["product_brief"]
        assert "name" in brief
        assert "problem_statement" in brief
        assert "target_personas" in brief
        assert "success_metrics" in brief
        assert isinstance(brief["target_personas"], list)
        assert isinstance(brief["success_metrics"], list)

    def test_given_missing_product_brief_input_when_called_then_raises_value_error(self):
        handler = StrategyHandler(_make_spec())
        with pytest.raises(ValueError, match="product_brief_input is required"):
            handler({})
