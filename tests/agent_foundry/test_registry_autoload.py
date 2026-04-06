"""Phase 1 — Registry auto-loading of built-in role specs.

Tests for RoleRegistry.with_builtins() and with_product_specs().
"""

import shutil
from pathlib import Path

import pytest

from agent_foundry.registry.errors import DuplicateRoleError
from agent_foundry.registry.registry import RoleRegistry
from agent_foundry.registry.spec import RoleSpec

FIXTURES = Path(__file__).parent / "fixtures"

_MINIMAL_SPEC_TEMPLATE = """\
name: {name}
description: Test product spec
version: "1.0.0"
implementation:
  module: fake.module
  class_name: FakeHandler
"""


class TestWithBuiltins:
    """RoleRegistry.with_builtins() loads framework specs automatically."""

    def test_given_with_builtins_called_when_len_checked_then_returns_8(self):
        registry = RoleRegistry.with_builtins()
        assert len(registry) == 8

    def test_given_with_builtins_called_when_get_schema_validator_then_returns_valid_spec(
        self,
    ):
        registry = RoleRegistry.with_builtins()
        spec = registry.get("schema_validator")
        assert spec is not None
        assert isinstance(spec, RoleSpec)
        assert spec.name == "schema_validator"

    def test_given_with_builtins_called_when_names_checked_then_contains_all_framework_specs(
        self,
    ):
        registry = RoleRegistry.with_builtins()
        names = sorted(registry.names())
        assert names == sorted(
            [
                "citation_validator",
                "evidence_first_contract",
                "human_approval_gate",
                "rag_retriever",
                "schema_validator",
                "structured_output_pydantic",
                "tool_calling",
                "uncertainty_completeness_validator",
            ]
        )


class TestWithProductSpecs:
    """RoleRegistry.with_product_specs() loads builtins + product specs."""

    @pytest.fixture
    def product_dir(self, tmp_path):
        """Create a temp directory with product-specific specs."""
        d = tmp_path / "capabilities"
        d.mkdir()
        for name in [
            "strategy_generate_product_brief",
            "architecture_generate_feature_arch",
            "spec_generate_feature_spec",
            "dev_implement_feature_tdd",
            "coding_implement_feature_from_spec",
        ]:
            (d / f"{name}.yaml").write_text(_MINIMAL_SPEC_TEMPLATE.format(name=name))
        return d

    def test_given_product_dir_with_5_specs_when_len_checked_then_returns_13(self, product_dir):
        registry = RoleRegistry.with_product_specs(product_dir)
        assert len(registry) == 13

    def test_given_product_dir_when_get_product_spec_then_returns_it(self, product_dir):
        registry = RoleRegistry.with_product_specs(product_dir)
        spec = registry.get("strategy_generate_product_brief")
        assert spec is not None
        assert spec.name == "strategy_generate_product_brief"

    def test_given_product_dir_when_get_builtin_spec_then_returns_it(self, product_dir):
        registry = RoleRegistry.with_product_specs(product_dir)
        spec = registry.get("schema_validator")
        assert spec is not None


class TestWithProductSpecsDuplicateDetection:
    """with_product_specs raises DuplicateRoleError on name collision."""

    @pytest.fixture
    def colliding_dir(self, tmp_path):
        """Create a product dir with a spec that collides with a builtin name."""
        d = tmp_path / "capabilities"
        d.mkdir()
        # Create a spec with the same name as a built-in
        builtin_caps = Path(__file__).parents[2] / "src" / "agent_foundry" / "roles"
        shutil.copy(builtin_caps / "schema_validator.yaml", d / "schema_validator.yaml")
        return d

    def test_given_product_spec_collides_with_builtin_when_with_product_specs_then_raises(
        self, colliding_dir
    ):
        with pytest.raises(DuplicateRoleError) as exc_info:
            RoleRegistry.with_product_specs(colliding_dir)
        assert "schema_validator" in str(exc_info.value)
