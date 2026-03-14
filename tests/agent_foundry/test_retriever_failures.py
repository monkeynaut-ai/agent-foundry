"""S2.5 — Robust failures: corrupted index + vector store outage.

Tests: missing/corrupt index raises IndexLoadError;
       backend down raises RetrieverUnavailableError.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_foundry.retriever.errors import IndexLoadError, RetrieverUnavailableError
from agent_foundry.retriever.indexer import RegistryIndexer


class TestCorruptedIndex:
    """Corrupted or missing index files produce typed errors."""

    def test_missing_index_raises_error(self, tmp_path):
        index_dir = tmp_path / "nonexistent"
        indexer = RegistryIndexer(index_dir=index_dir)
        with pytest.raises(IndexLoadError) as exc_info:
            indexer.load()
        assert "nonexistent" in str(exc_info.value) or exc_info.value.index_path is not None

    def test_corrupted_index_raises_error(self, tmp_path):
        index_dir = tmp_path / "corrupt"
        index_dir.mkdir()
        (index_dir / "index.faiss").write_text("not a valid faiss index")
        (index_dir / "index.pkl").write_text("not a valid pickle")
        indexer = RegistryIndexer(index_dir=index_dir)
        with pytest.raises(IndexLoadError):
            indexer.load()

    def test_error_includes_index_path(self, tmp_path):
        index_dir = tmp_path / "missing"
        indexer = RegistryIndexer(index_dir=index_dir)
        with pytest.raises(IndexLoadError) as exc_info:
            indexer.load()
        assert exc_info.value.index_path == index_dir


class TestBackendOutage:
    """Vector store backend failures produce typed errors."""

    def test_retrieve_on_unloaded_store_raises_error(self, tmp_path):
        index_dir = tmp_path / "empty"
        indexer = RegistryIndexer(index_dir=index_dir)
        with pytest.raises(RetrieverUnavailableError):
            indexer.retrieve("test query")

    def test_faiss_error_during_search_raises_error(self, tmp_path):
        """Simulate FAISS backend error during search."""
        from agent_foundry.registry.registry import CapabilityRegistry

        caps_dir = Path(__file__).parent.parent.parent / "src" / "agent_foundry" / "capabilities"
        registry = CapabilityRegistry.from_directory(caps_dir)

        index_dir = tmp_path / "index"
        indexer = RegistryIndexer(index_dir=index_dir)
        indexer.build(registry)

        # Simulate backend failure
        indexer._store.similarity_search = MagicMock(
            side_effect=RuntimeError("FAISS internal error")
        )
        with pytest.raises(RetrieverUnavailableError) as exc_info:
            indexer.retrieve("rag_retriever")
        assert "FAISS" in str(exc_info.value) or exc_info.value.__cause__ is not None
