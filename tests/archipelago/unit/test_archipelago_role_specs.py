"""Archipelago role specs — loading, schema validation, and registry integration."""

import jsonschema

from agent_foundry.registry.spec import RoleSpec, load_role_spec
from archipelago.models import (
    CodePatch,
    FeatureArchitecture,
    FeatureSpec,
    ProductBrief,
    TestPlan,
    TestResults,
)

from ..conftest import PRODUCT_ROLES_DIR

ARCHIPELAGO_SPEC_NAMES = [
    "architecture_generate_feature_arch",
    "code_implement_from_tests",
    "coding_implement_feature_from_spec",
    "dev_implement_feature_tdd",
    "spec_generate_feature_spec",
    "strategy_generate_product_brief",
    "write_unit_tests_from_spec",
]


def _valid_product_brief_dump() -> dict:
    return ProductBrief(
        name="Test Product",
        problem_statement="A test problem",
        target_personas=["engineer"],
        success_metrics=["metric-1"],
    ).model_dump()


def _valid_feature_architecture_dump() -> dict:
    return FeatureArchitecture(
        feature_name="Test Feature",
        components=["comp-a"],
        data_flow="a -> b",
        technology_choices=["Python"],
    ).model_dump()


def _valid_feature_spec_dump() -> dict:
    return FeatureSpec(
        title="Test Spec",
        objective="Test objective",
        acceptance_criteria=["criterion-1"],
        pr_slices=[{"title": "slice-1", "commits": ["c1"]}],
    ).model_dump()


def _valid_test_plan_dump() -> dict:
    return TestPlan(
        feature_name="Test Feature",
        test_cases=[{"name": "test_one", "type": "unit"}],
        coverage_targets=["handler"],
    ).model_dump()


def _valid_code_patch_dump() -> dict:
    return CodePatch(
        feature_name="Test Feature",
        files_changed=["src/foo.py"],
        diff_summary="Added foo",
        branch_name="feat/foo",
    ).model_dump()


def _valid_test_results_dump() -> dict:
    return TestResults(
        feature_name="Test Feature",
        tests_passed=5,
        tests_failed=0,
        test_output="5 passed",
        all_green=True,
    ).model_dump()


# ── Commit 1: Strategy and Architecture spec loading + schema validation ──


class TestStrategySpec:
    def test_given_yaml_file_when_loaded_then_returns_valid_role_spec(self):
        spec = load_role_spec(PRODUCT_ROLES_DIR / "strategy_generate_product_brief.yaml")
        assert isinstance(spec, RoleSpec)
        assert spec.name == "strategy_generate_product_brief"
        assert spec.version == "1.0.0"
        assert "archipelago" in spec.tags

    def test_given_strategy_spec_when_outputs_schema_validates_model_dump_then_passes(
        self,
    ):
        spec = load_role_spec(PRODUCT_ROLES_DIR / "strategy_generate_product_brief.yaml")
        data = {"product_brief": _valid_product_brief_dump()}
        jsonschema.validate(data, spec.outputs_schema)


class TestArchitectureSpec:
    def test_given_yaml_file_when_loaded_then_returns_valid_role_spec(self):
        spec = load_role_spec(PRODUCT_ROLES_DIR / "architecture_generate_feature_arch.yaml")
        assert isinstance(spec, RoleSpec)
        assert spec.name == "architecture_generate_feature_arch"
        assert spec.version == "1.0.0"
        assert "archipelago" in spec.tags

    def test_given_architecture_spec_when_outputs_schema_validates_model_dump_then_passes(
        self,
    ):
        spec = load_role_spec(PRODUCT_ROLES_DIR / "architecture_generate_feature_arch.yaml")
        data = {"feature_architecture": _valid_feature_architecture_dump()}
        jsonschema.validate(data, spec.outputs_schema)


# ── Commit 2: Spec and Dev/Test spec loading + schema validation ──


class TestSpecSpec:
    def test_given_yaml_file_when_loaded_then_returns_valid_role_spec(self):
        spec = load_role_spec(PRODUCT_ROLES_DIR / "spec_generate_feature_spec.yaml")
        assert isinstance(spec, RoleSpec)
        assert spec.name == "spec_generate_feature_spec"
        assert spec.version == "1.0.0"
        assert "archipelago" in spec.tags

    def test_given_spec_spec_when_outputs_schema_validates_model_dump_then_passes(
        self,
    ):
        spec = load_role_spec(PRODUCT_ROLES_DIR / "spec_generate_feature_spec.yaml")
        data = {
            "feature_spec": _valid_feature_spec_dump(),
            "test_plan": _valid_test_plan_dump(),
        }
        jsonschema.validate(data, spec.outputs_schema)


class TestDevSpec:
    def test_given_yaml_file_when_loaded_then_returns_valid_role_spec(self):
        spec = load_role_spec(PRODUCT_ROLES_DIR / "dev_implement_feature_tdd.yaml")
        assert isinstance(spec, RoleSpec)
        assert spec.name == "dev_implement_feature_tdd"
        assert spec.version == "1.0.0"
        assert "archipelago" in spec.tags

    def test_given_dev_spec_when_outputs_schema_validates_model_dump_then_passes(self):
        spec = load_role_spec(PRODUCT_ROLES_DIR / "dev_implement_feature_tdd.yaml")
        data = {
            "code_patch": _valid_code_patch_dump(),
            "test_results": _valid_test_results_dump(),
        }
        jsonschema.validate(data, spec.outputs_schema)


# ── Unit test writer and code writer specs ──


class TestUnitTestWriterSpec:
    def test_given_yaml_file_when_loaded_then_returns_valid_role_spec(self):
        spec = load_role_spec(PRODUCT_ROLES_DIR / "write_unit_tests_from_spec.yaml")
        assert isinstance(spec, RoleSpec)
        assert spec.name == "write_unit_tests_from_spec"
        assert spec.version == "1.0.0"
        assert "archipelago" in spec.tags
        assert "unit-test" in spec.tags

    def test_given_spec_when_outputs_schema_validates_then_passes(self):
        spec = load_role_spec(PRODUCT_ROLES_DIR / "write_unit_tests_from_spec.yaml")
        data = {
            "result_summary": "Tests written",
            "workspace_ref": "/workspace",
            "workspace_volume": "archipelago-123",
            "patches": [],
            "evidence": [],
            "status": "completed",
        }
        jsonschema.validate(data, spec.outputs_schema)


class TestCodeWriterSpec:
    def test_given_yaml_file_when_loaded_then_returns_valid_role_spec(self):
        spec = load_role_spec(PRODUCT_ROLES_DIR / "code_implement_from_tests.yaml")
        assert isinstance(spec, RoleSpec)
        assert spec.name == "code_implement_from_tests"
        assert spec.version == "1.0.0"
        assert "archipelago" in spec.tags

    def test_given_spec_when_inputs_require_workspace_volume(self):
        spec = load_role_spec(PRODUCT_ROLES_DIR / "code_implement_from_tests.yaml")
        assert "workspace_volume" in spec.inputs_schema["required"]

    def test_given_spec_when_outputs_schema_validates_then_passes(self):
        spec = load_role_spec(PRODUCT_ROLES_DIR / "code_implement_from_tests.yaml")
        data = {
            "result_summary": "Code implemented",
            "workspace_ref": "/workspace",
            "patches": [],
            "evidence": [],
            "status": "completed",
        }
        jsonschema.validate(data, spec.outputs_schema)


# ── Commit 3: Registry integration and tag search ──


class TestRegistryIntegration:
    def test_given_all_yaml_specs_when_registry_loaded_then_contains_15_capabilities(
        self, registry
    ):
        assert len(registry) == 15

    def test_given_registry_when_searched_by_archipelago_tag_then_returns_exactly_7(self, registry):
        results = registry.search(tags=["archipelago"])
        assert len(results) == 7

    def test_given_each_archipelago_spec_when_name_queried_then_found_in_registry(self, registry):
        for name in ARCHIPELAGO_SPEC_NAMES:
            assert registry.get(name) is not None, f"Missing role: {name}"

    def test_given_archipelago_tag_search_then_results_sorted_by_name(self, registry):
        results = registry.search(tags=["archipelago"])
        names = [s.name for s in results]
        assert names == sorted(names)

    def test_given_archipelago_tag_search_then_returns_only_archipelago_specs(self, registry):
        results = registry.search(tags=["archipelago"])
        names = {s.name for s in results}
        assert names == set(ARCHIPELAGO_SPEC_NAMES)
