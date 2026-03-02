"""S2.2 — Deterministic retrieval ordering + stable IDs.

Tests: same query twice returns identical ids + ordering;
       rerun indexing yields identical doc ids.
Feature flag: FF_DETERMINISTIC_RETRIEVAL (default on).
"""

from pathlib import Path

import pytest

from agent_foundry.registry.registry import CapabilityRegistry
from agent_foundry.retriever.indexer import RegistryIndexer

CAPABILITIES_DIR = Path(__file__).parent.parent.parent / "capabilities"


@pytest.fixture
def registry():
    return CapabilityRegistry.from_directory(CAPABILITIES_DIR)


@pytest.fixture
def built_indexer(registry, tmp_path):
    index_dir = tmp_path / "index"
    indexer = RegistryIndexer(index_dir=index_dir)
    indexer.build(registry)
    return indexer


class TestDeterministicRetrieval:
    """Same query returns identical results every time."""

    def test_same_query_returns_identical_ids(self, built_indexer):
        results1 = built_indexer.retrieve("rag_retriever", k=3)
        results2 = built_indexer.retrieve("rag_retriever", k=3)
        ids1 = [r.metadata["chunk_id"] for r in results1]
        ids2 = [r.metadata["chunk_id"] for r in results2]
        assert ids1 == ids2

    def test_same_query_returns_identical_ordering(self, built_indexer):
        results1 = built_indexer.retrieve("schema validation", k=5)
        results2 = built_indexer.retrieve("schema validation", k=5)
        contents1 = [r.page_content for r in results1]
        contents2 = [r.page_content for r in results2]
        assert contents1 == contents2


class TestStableIds:
    """Rerun indexing produces identical document IDs."""

    def test_reindex_yields_identical_chunk_ids(self, registry, tmp_path):
        dir1 = tmp_path / "index1"
        indexer1 = RegistryIndexer(index_dir=dir1)
        indexer1.build(registry)
        ids1 = set()
        for name in sorted(registry.names()):
            results = indexer1.retrieve(name, k=1)
            for r in results:
                ids1.add(r.metadata["chunk_id"])

        dir2 = tmp_path / "index2"
        indexer2 = RegistryIndexer(index_dir=dir2)
        indexer2.build(registry)
        ids2 = set()
        for name in sorted(registry.names()):
            results = indexer2.retrieve(name, k=1)
            for r in results:
                ids2.add(r.metadata["chunk_id"])

        assert ids1 == ids2
