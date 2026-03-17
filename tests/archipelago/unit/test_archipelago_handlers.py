"""Archipelago handlers — unit tests."""

from archipelago.handlers import (
    ARCHIPELAGO_HANDLERS,
    spec_approval_gate_handler,
)
from archipelago.models import FeatureSpec


def _mock_feature_spec():
    return FeatureSpec(
        title="Test Runner MVP",
        objective="Run tests and report results",
        acceptance_criteria=["All tests run", "Coverage reported"],
        pr_slices=[{"title": "Core runner", "commits": ["Add executor"]}],
    )


class TestGateHandler:
    def test_given_state_with_spec_when_gate_called_then_returns_approved(self):
        state = {"feature_spec": _mock_feature_spec().model_dump()}
        result = spec_approval_gate_handler(state)
        assert result["approved"] is True
        assert result["approver"] == "auto"


class TestHandlerRegistry:
    def test_given_archipelago_handlers_when_all_keys_checked_then_all_capabilities_present(
        self,
    ):
        expected = {
            "coding_implement_feature_from_spec",
            "write_unit_tests_from_spec",
            "code_implement_from_tests",
        }
        assert set(ARCHIPELAGO_HANDLERS.keys()) == expected

    def test_given_each_handler_in_registry_when_checked_then_is_callable(self):
        for name, handler in ARCHIPELAGO_HANDLERS.items():
            assert callable(handler), f"Handler for {name} is not callable"
