"""Phase 1 — Registry auto-loading of built-in capability specs.

Tests for CapabilityRegistry.with_builtins() and with_product_specs().
"""

import shutil
from pathlib import Path

import pytest

from agent_foundry.registry.errors import DuplicateCapabilityError
from agent_foundry.registry.registry import CapabilityRegistry
from agent_foundry.registry.spec import CapabilitySpec

FIXTURES = Path(__file__).parent / "fixtures"


class TestWithBuiltins:
    """CapabilityRegistry.with_builtins() loads framework specs automatically."""

    def test_given_with_builtins_called_when_len_checked_then_returns_8(self):
        registry = CapabilityRegistry.with_builtins()
        assert len(registry) == 8

    def test_given_with_builtins_called_when_get_schema_validator_then_returns_valid_spec(
        self,
    ):
        registry = CapabilityRegistry.with_builtins()
        spec = registry.get("schema_validator")
        assert spec is not None
        assert isinstance(spec, CapabilitySpec)
        assert spec.name == "schema_validator"

    def test_given_with_builtins_called_when_names_checked_then_contains_all_framework_specs(
        self,
    ):
        registry = CapabilityRegistry.with_builtins()
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
    """CapabilityRegistry.with_product_specs() loads builtins + product specs."""

    @pytest.fixture
    def product_dir(self, tmp_path):
        """Create a temp directory with product-specific specs."""
        d = tmp_path / "capabilities"
        d.mkdir()
        # Copy Archipelago specs as product specs
        repo_caps = Path(__file__).parents[2] / "src" / "archipelago" / "capabilities"
        for name in [
            "strategy_generate_product_brief.yaml",
            "architecture_generate_feature_arch.yaml",
            "spec_generate_feature_spec.yaml",
            "dev_implement_feature_tdd.yaml",
            "coding_implement_feature_from_spec.yaml",
        ]:
            shutil.copy(repo_caps / name, d / name)
        return d

    def test_given_product_dir_with_5_specs_when_len_checked_then_returns_13(self, product_dir):
        registry = CapabilityRegistry.with_product_specs(product_dir)
        assert len(registry) == 13

    def test_given_product_dir_when_get_product_spec_then_returns_it(self, product_dir):
        registry = CapabilityRegistry.with_product_specs(product_dir)
        spec = registry.get("strategy_generate_product_brief")
        assert spec is not None
        assert spec.name == "strategy_generate_product_brief"

    def test_given_product_dir_when_get_builtin_spec_then_returns_it(self, product_dir):
        registry = CapabilityRegistry.with_product_specs(product_dir)
        spec = registry.get("schema_validator")
        assert spec is not None


class TestWithProductSpecsDuplicateDetection:
    """with_product_specs raises DuplicateCapabilityError on name collision."""

    @pytest.fixture
    def colliding_dir(self, tmp_path):
        """Create a product dir with a spec that collides with a builtin name."""
        d = tmp_path / "capabilities"
        d.mkdir()
        # Create a spec with the same name as a built-in
        builtin_caps = Path(__file__).parents[2] / "src" / "agent_foundry" / "capabilities"
        shutil.copy(builtin_caps / "schema_validator.yaml", d / "schema_validator.yaml")
        return d

    def test_given_product_spec_collides_with_builtin_when_with_product_specs_then_raises(
        self, colliding_dir
    ):
        with pytest.raises(DuplicateCapabilityError) as exc_info:
            CapabilityRegistry.with_product_specs(colliding_dir)
        assert "schema_validator" in str(exc_info.value)
