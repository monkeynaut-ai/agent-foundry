"""Archipelago artifact models — validation and round-trip tests."""

import pytest
from pydantic import ValidationError

from archipelago.models import (
    CodePatch,
    FeatureArchitecture,
    FeatureSpec,
    ProductBrief,
    TestPlan,
    TestResults,
)


def _valid_product_brief() -> dict:
    return {
        "name": "Archipelago Orchestrator",
        "problem_statement": "Manual inter-agent routing is brittle and unobservable",
        "target_personas": ["platform engineer", "product manager"],
        "success_metrics": ["end-to-end pipeline runs without manual intervention"],
    }


def _valid_feature_architecture() -> dict:
    return {
        "feature_name": "Pipeline Orchestrator",
        "components": ["capability registry", "plan compiler", "execution engine"],
        "data_flow": "strategy -> architecture -> spec -> dev/test",
        "technology_choices": ["LangGraph", "Pydantic", "langchain-anthropic"],
    }


class TestProductBrief:
    def test_given_valid_fields_when_instantiated_then_validates(self):
        brief = ProductBrief(**_valid_product_brief())
        assert brief.name == "Archipelago Orchestrator"
        assert brief.problem_statement == "Manual inter-agent routing is brittle and unobservable"
        assert len(brief.target_personas) == 2
        assert len(brief.success_metrics) == 1
        assert brief.constraints == []

    def test_given_valid_instance_when_json_round_tripped_then_no_field_loss(self):
        brief = ProductBrief(**_valid_product_brief())
        json_str = brief.model_dump_json()
        reconstructed = ProductBrief.model_validate_json(json_str)
        assert reconstructed == brief

    def test_given_missing_required_field_when_instantiated_then_raises_validation_error(self):
        data = _valid_product_brief()
        del data["name"]
        with pytest.raises(ValidationError) as exc_info:
            ProductBrief(**data)
        field_names = [e["loc"][0] for e in exc_info.value.errors()]
        assert "name" in field_names


class TestFeatureArchitecture:
    def test_given_valid_fields_when_instantiated_then_validates(self):
        arch = FeatureArchitecture(**_valid_feature_architecture())
        assert arch.feature_name == "Pipeline Orchestrator"
        assert len(arch.components) == 3
        assert arch.data_flow == "strategy -> architecture -> spec -> dev/test"
        assert len(arch.technology_choices) == 3
        assert arch.risks == []

    def test_given_valid_instance_when_json_round_tripped_then_no_field_loss(self):
        arch = FeatureArchitecture(**_valid_feature_architecture())
        json_str = arch.model_dump_json()
        reconstructed = FeatureArchitecture.model_validate_json(json_str)
        assert reconstructed == arch

    def test_given_missing_required_field_when_instantiated_then_raises_validation_error(self):
        data = _valid_feature_architecture()
        del data["feature_name"]
        with pytest.raises(ValidationError) as exc_info:
            FeatureArchitecture(**data)
        field_names = [e["loc"][0] for e in exc_info.value.errors()]
        assert "feature_name" in field_names


def _valid_feature_spec() -> dict:
    return {
        "title": "Pipeline Orchestrator MVP",
        "objective": "Replace manual inter-agent routing with compiled DAG execution",
        "acceptance_criteria": [
            "Pipeline runs end-to-end without manual intervention",
            "All artifacts validate against schemas",
        ],
        "pr_slices": [
            {"title": "State models", "commits": ["Add ProductBrief model"]},
        ],
    }


def _valid_test_plan() -> dict:
    return {
        "feature_name": "Pipeline Orchestrator",
        "test_cases": [
            {"name": "test_strategy_produces_brief", "type": "unit"},
        ],
        "coverage_targets": ["strategy handler", "architecture handler"],
    }


def _valid_code_patch() -> dict:
    return {
        "feature_name": "Pipeline Orchestrator",
        "files_changed": ["src/archipelago/handlers.py", "src/archipelago/runner.py"],
        "diff_summary": "Added strategy and architecture handlers",
        "branch_name": "feat/archipelago-handlers",
    }


def _valid_test_results() -> dict:
    return {
        "feature_name": "Pipeline Orchestrator",
        "tests_passed": 12,
        "tests_failed": 0,
        "test_output": "12 passed in 0.5s",
        "all_green": True,
    }


class TestFeatureSpec:
    def test_given_valid_fields_when_instantiated_then_validates(self):
        spec = FeatureSpec(**_valid_feature_spec())
        assert spec.title == "Pipeline Orchestrator MVP"
        assert len(spec.acceptance_criteria) == 2
        assert len(spec.pr_slices) == 1

    def test_given_valid_instance_when_json_round_tripped_then_no_field_loss(self):
        spec = FeatureSpec(**_valid_feature_spec())
        json_str = spec.model_dump_json()
        reconstructed = FeatureSpec.model_validate_json(json_str)
        assert reconstructed == spec

    def test_given_missing_required_field_when_instantiated_then_raises_validation_error(self):
        data = _valid_feature_spec()
        del data["title"]
        with pytest.raises(ValidationError) as exc_info:
            FeatureSpec(**data)
        field_names = [e["loc"][0] for e in exc_info.value.errors()]
        assert "title" in field_names


class TestTestPlan:
    def test_given_valid_fields_when_instantiated_then_validates(self):
        plan = TestPlan(**_valid_test_plan())
        assert plan.feature_name == "Pipeline Orchestrator"
        assert len(plan.test_cases) == 1
        assert len(plan.coverage_targets) == 2

    def test_given_valid_instance_when_json_round_tripped_then_no_field_loss(self):
        plan = TestPlan(**_valid_test_plan())
        json_str = plan.model_dump_json()
        reconstructed = TestPlan.model_validate_json(json_str)
        assert reconstructed == plan


class TestCodePatch:
    def test_given_valid_fields_when_instantiated_then_validates(self):
        patch = CodePatch(**_valid_code_patch())
        assert patch.feature_name == "Pipeline Orchestrator"
        assert len(patch.files_changed) == 2
        assert patch.branch_name == "feat/archipelago-handlers"

    def test_given_valid_instance_when_json_round_tripped_then_no_field_loss(self):
        patch = CodePatch(**_valid_code_patch())
        json_str = patch.model_dump_json()
        reconstructed = CodePatch.model_validate_json(json_str)
        assert reconstructed == patch


class TestTestResults:
    def test_given_valid_fields_when_instantiated_then_validates(self):
        results = TestResults(**_valid_test_results())
        assert results.tests_passed == 12
        assert results.tests_failed == 0
        assert results.all_green is True

    def test_given_valid_instance_when_json_round_tripped_then_no_field_loss(self):
        results = TestResults(**_valid_test_results())
        json_str = results.model_dump_json()
        reconstructed = TestResults.model_validate_json(json_str)
        assert reconstructed == results

    def test_given_missing_required_field_when_instantiated_then_raises_validation_error(self):
        data = _valid_test_results()
        del data["all_green"]
        with pytest.raises(ValidationError) as exc_info:
            TestResults(**data)
        field_names = [e["loc"][0] for e in exc_info.value.errors()]
        assert "all_green" in field_names
