"""S2.3 — Retrieval API returns capability snippets for exact name queries.

Tests: query="rag_retriever" returns snippet referencing that spec in top-3.
Feature flag: FF_RETRIEVER (default on after this slice).
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from agent_foundry.registry.registry import CapabilityRegistry
from agent_foundry.retriever.indexer import RegistryIndexer
from agent_foundry.retriever.retrieval import RetrievalAPI

CAPABILITIES_DIR = Path(__file__).parent.parent / "capabilities"


@pytest.fixture
def registry():
    return CapabilityRegistry.from_directory(CAPABILITIES_DIR)


@pytest.fixture
def retrieval_api(registry, tmp_path):
    index_dir = tmp_path / "index"
    indexer = RegistryIndexer(index_dir=index_dir)
    indexer.build(registry)
    return RetrievalAPI(indexer=indexer)


class TestExactNameQuery:
    """Exact capability name queries return relevant snippets."""

    def test_rag_retriever_in_top_3(self, retrieval_api):
        snippets = retrieval_api.retrieve("rag_retriever")
        sources = [s.metadata.get("source", "") for s in snippets]
        assert any("rag_retriever" in src for src in sources)

    def test_schema_validator_in_top_3(self, retrieval_api):
        snippets = retrieval_api.retrieve("schema_validator")
        sources = [s.metadata.get("source", "") for s in snippets]
        assert any("schema_validator" in src for src in sources)

    def test_returns_at_most_k_snippets(self, retrieval_api):
        snippets = retrieval_api.retrieve("rag_retriever", k=2)
        assert len(snippets) <= 2

    def test_default_returns_3_snippets(self, retrieval_api):
        snippets = retrieval_api.retrieve("rag_retriever")
        assert len(snippets) == 3

    def test_snippets_have_content(self, retrieval_api):
        snippets = retrieval_api.retrieve("rag_retriever")
        for s in snippets:
            assert s.page_content.strip() != ""

    def test_snippets_have_metadata(self, retrieval_api):
        snippets = retrieval_api.retrieve("rag_retriever")
        for s in snippets:
            assert "source" in s.metadata
            assert "chunk_id" in s.metadata


class TestFeatureFlag:
    """FF_RETRIEVER controls retrieval availability."""

    def test_flag_off_raises_error(self, retrieval_api):
        with patch("agent_foundry.retriever.retrieval.FF_RETRIEVER", False):
            with pytest.raises(RuntimeError, match="retriever.*disabled"):
                retrieval_api.retrieve("rag_retriever")

    def test_flag_on_works(self, retrieval_api):
        with patch("agent_foundry.retriever.retrieval.FF_RETRIEVER", True):
            snippets = retrieval_api.retrieve("rag_retriever")
            assert len(snippets) > 0
