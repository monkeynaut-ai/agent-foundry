"""Archipelago handlers — unit tests with mocked LLM."""

from unittest.mock import MagicMock, patch

import jsonschema
import pytest

from agent_foundry.registry.spec import load_capability_spec
from archipelago.handlers import (
    ARCHIPELAGO_HANDLERS,
    architecture_handler,
    dev_test_handler,
    spec_approval_gate_handler,
    spec_handler,
    strategy_handler,
)
from archipelago.models import (
    CodePatch,
    FeatureArchitecture,
    FeatureSpec,
    ProductBrief,
    TestPlan,
    TestResults,
)

from .conftest import PRODUCT_CAPS_DIR


def _mock_product_brief():
    return ProductBrief(
        name="Test Product",
        problem_statement="Solve testing problems",
        target_personas=["developer", "QA engineer"],
        success_metrics=["90% test coverage"],
        constraints=["Python only"],
    )


def _mock_feature_architecture():
    return FeatureArchitecture(
        feature_name="Test Runner",
        components=["executor", "reporter"],
        data_flow="tests -> executor -> reporter",
        technology_choices=["pytest", "coverage.py"],
        risks=["Flaky tests"],
    )


def _mock_feature_spec():
    return FeatureSpec(
        title="Test Runner MVP",
        objective="Run tests and report results",
        acceptance_criteria=["All tests run", "Coverage reported"],
        pr_slices=[{"title": "Core runner", "commits": ["Add executor"]}],
    )


def _mock_test_plan():
    return TestPlan(
        feature_name="Test Runner",
        test_cases=[{"name": "test_executor_runs", "type": "unit"}],
        coverage_targets=["executor", "reporter"],
    )


def _mock_code_patch():
    return CodePatch(
        feature_name="Test Runner",
        files_changed=["src/runner.py"],
        diff_summary="Added test executor",
        branch_name="feat/test-runner",
    )


def _mock_test_results():
    return TestResults(
        feature_name="Test Runner",
        tests_passed=5,
        tests_failed=0,
        test_output="5 passed in 0.3s",
        all_green=True,
    )


def _mock_llm(mock_get_llm, return_value):
    """Configure mock LLM to return a structured output value."""
    mock = MagicMock()
    mock.with_structured_output.return_value = mock
    mock.invoke.return_value = return_value
    mock_get_llm.return_value = mock
    return mock


class TestStrategyHandler:
    @patch("archipelago.handlers._get_llm")
    def test_given_valid_input_when_handler_called_then_state_contains_product_brief(
        self, mock_get_llm
    ):
        _mock_llm(mock_get_llm, _mock_product_brief())

        state = {"product_brief_input": "Build a test runner"}
        result = strategy_handler(state)
        assert "product_brief" in result
        assert result["product_brief"]["name"] == "Test Product"

    @patch("archipelago.handlers._get_llm")
    def test_given_valid_input_when_handler_called_then_product_brief_validates_against_schema(
        self, mock_get_llm
    ):
        _mock_llm(mock_get_llm, _mock_product_brief())

        state = {"product_brief_input": "Build a test runner"}
        result = strategy_handler(state)

        spec = load_capability_spec(PRODUCT_CAPS_DIR / "strategy_generate_product_brief.yaml")
        jsonschema.validate({"product_brief": result["product_brief"]}, spec.outputs_schema)

    def test_given_empty_input_when_handler_called_then_raises_value_error(self):
        state = {"product_brief_input": ""}
        with pytest.raises(ValueError, match="product_brief_input is required"):
            strategy_handler(state)


class TestArchitectureHandler:
    @patch("archipelago.handlers._get_llm")
    def test_given_state_with_product_brief_when_called_then_state_contains_feature_architecture(
        self, mock_get_llm
    ):
        _mock_llm(mock_get_llm, _mock_feature_architecture())

        state = {"product_brief": _mock_product_brief().model_dump()}
        result = architecture_handler(state)
        assert "feature_architecture" in result
        assert result["feature_architecture"]["feature_name"] == "Test Runner"

    @patch("archipelago.handlers._get_llm")
    def test_given_state_with_product_brief_when_called_then_feature_architecture_validates(
        self, mock_get_llm
    ):
        _mock_llm(mock_get_llm, _mock_feature_architecture())

        state = {"product_brief": _mock_product_brief().model_dump()}
        result = architecture_handler(state)

        spec = load_capability_spec(PRODUCT_CAPS_DIR / "architecture_generate_feature_arch.yaml")
        jsonschema.validate(
            {"feature_architecture": result["feature_architecture"]}, spec.outputs_schema
        )


class TestSpecHandler:
    @patch("archipelago.handlers._get_llm")
    def test_given_state_with_architecture_when_called_then_state_contains_feature_spec_and_test_plan(
        self, mock_get_llm
    ):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = f'{{"feature_spec": {_mock_feature_spec().model_dump_json()}, "test_plan": {_mock_test_plan().model_dump_json()}}}'
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        state = {"feature_architecture": _mock_feature_architecture().model_dump()}
        result = spec_handler(state)
        assert "feature_spec" in result
        assert "test_plan" in result

    @patch("archipelago.handlers._get_llm")
    def test_given_state_with_architecture_when_called_then_both_outputs_validate(
        self, mock_get_llm
    ):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = f'{{"feature_spec": {_mock_feature_spec().model_dump_json()}, "test_plan": {_mock_test_plan().model_dump_json()}}}'
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        state = {"feature_architecture": _mock_feature_architecture().model_dump()}
        result = spec_handler(state)

        spec = load_capability_spec(PRODUCT_CAPS_DIR / "spec_generate_feature_spec.yaml")
        combined = {"feature_spec": result["feature_spec"], "test_plan": result["test_plan"]}
        jsonschema.validate(combined, spec.outputs_schema)


class TestDevTestHandler:
    @patch("archipelago.handlers._get_llm")
    def test_given_state_with_spec_and_plan_when_called_then_state_contains_code_patch_and_test_results(
        self, mock_get_llm
    ):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = f'{{"code_patch": {_mock_code_patch().model_dump_json()}, "test_results": {_mock_test_results().model_dump_json()}}}'
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        state = {
            "feature_spec": _mock_feature_spec().model_dump(),
            "test_plan": _mock_test_plan().model_dump(),
        }
        result = dev_test_handler(state)
        assert "code_patch" in result
        assert "test_results" in result

    @patch("archipelago.handlers._get_llm")
    def test_given_state_with_spec_and_plan_when_called_then_both_outputs_validate(
        self, mock_get_llm
    ):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = f'{{"code_patch": {_mock_code_patch().model_dump_json()}, "test_results": {_mock_test_results().model_dump_json()}}}'
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        state = {
            "feature_spec": _mock_feature_spec().model_dump(),
            "test_plan": _mock_test_plan().model_dump(),
        }
        result = dev_test_handler(state)

        spec = load_capability_spec(PRODUCT_CAPS_DIR / "dev_implement_feature_tdd.yaml")
        combined = {"code_patch": result["code_patch"], "test_results": result["test_results"]}
        jsonschema.validate(combined, spec.outputs_schema)


class TestGateHandler:
    def test_given_state_with_spec_when_gate_called_then_returns_approved(self):
        state = {"feature_spec": _mock_feature_spec().model_dump()}
        result = spec_approval_gate_handler(state)
        assert result["approved"] is True
        assert result["approver"] == "auto"


class TestHandlerRegistry:
    def test_given_archipelago_handlers_when_all_keys_checked_then_all_2_capabilities_present(
        self,
    ):
        expected = {
            "dev_implement_feature_tdd",
            "coding_implement_feature_from_spec",
        }
        assert set(ARCHIPELAGO_HANDLERS.keys()) == expected

    def test_given_each_handler_in_registry_when_checked_then_is_callable(self):
        for name, handler in ARCHIPELAGO_HANDLERS.items():
            assert callable(handler), f"Handler for {name} is not callable"
