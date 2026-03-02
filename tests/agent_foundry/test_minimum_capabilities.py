"""S1.7 — Minimum capability set present + searchable by tags.

Tests: registry contains all minimum capability names;
       tag search returns correct set sorted deterministically.
Feature flag: FF_MIN_CAP_SET (default on).
"""

from pathlib import Path

import pytest

from agent_foundry.registry.registry import CapabilityRegistry

CAPABILITIES_DIR = Path(__file__).parent.parent.parent / "capabilities"

MINIMUM_CAPABILITIES = [
    "citation_validator",
    "evidence_first_contract",
    "human_approval_gate",
    "rag_retriever",
    "schema_validator",
    "structured_output_pydantic",
    "tool_calling",
    "uncertainty_completeness_validator",
]


@pytest.fixture
def registry():
    return CapabilityRegistry.from_directory(CAPABILITIES_DIR)


class TestMinimumCapabilitySet:
    """All required minimum capabilities are present."""

    @pytest.mark.parametrize("name", MINIMUM_CAPABILITIES)
    def test_capability_present(self, registry, name):
        assert registry.get(name) is not None, f"Missing capability: {name}"

    def test_minimum_set_count(self, registry):
        assert len(registry) >= len(MINIMUM_CAPABILITIES)


class TestSearchByTags:
    """Tag-based search returns correct results in deterministic order."""

    def test_search_validation_tag_returns_validators(self, registry):
        results = registry.search(tags=["validation"])
        names = [s.name for s in results]
        assert "schema_validator" in names
        assert "citation_validator" in names
        assert "uncertainty_completeness_validator" in names
        assert "evidence_first_contract" in names

    def test_search_eval_gate_tag(self, registry):
        results = registry.search(tags=["eval_gate"])
        names = [s.name for s in results]
        assert "schema_validator" in names
        assert "citation_validator" in names

    def test_search_retrieval_tag(self, registry):
        results = registry.search(tags=["retrieval"])
        names = [s.name for s in results]
        assert "rag_retriever" in names

    def test_search_no_matching_tag_returns_empty(self, registry):
        results = registry.search(tags=["nonexistent_tag"])
        assert results == []

    def test_search_results_sorted_by_name(self, registry):
        results = registry.search(tags=["validation"])
        names = [s.name for s in results]
        assert names == sorted(names)

    def test_search_deterministic_ordering(self, registry):
        results1 = registry.search(tags=["validation"])
        results2 = registry.search(tags=["validation"])
        assert [s.name for s in results1] == [s.name for s in results2]

    def test_search_multiple_tags_intersects(self, registry):
        results = registry.search(tags=["validation", "citation"])
        names = [s.name for s in results]
        assert "citation_validator" in names
        # rag_retriever doesn't have both tags
        assert "rag_retriever" not in names
