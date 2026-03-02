"""S2.1 — Corpus ingestion + persisted index (happy path).

Tests: build index creates files; reload works; rebuild not required.
Feature flag: FF_RETRIEVER (default off until S2.3).
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
def index_dir(tmp_path):
    return tmp_path / "index"


class TestCorpusIngestion:
    """Build an index from registry specs and curated docs."""

    def test_build_index_creates_files(self, registry, index_dir):
        indexer = RegistryIndexer(index_dir=index_dir)
        indexer.build(registry)
        assert index_dir.exists()
        assert any(index_dir.iterdir())

    def test_build_index_with_docs(self, registry, index_dir, tmp_path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "guide.md").write_text("# How to use RAG\nUse rag_retriever capability.")
        indexer = RegistryIndexer(index_dir=index_dir)
        indexer.build(registry, docs_dir=docs_dir)
        assert index_dir.exists()


class TestPersistence:
    """Index can be persisted and reloaded without rebuild."""

    def test_reload_without_rebuild(self, registry, index_dir):
        indexer = RegistryIndexer(index_dir=index_dir)
        indexer.build(registry)

        indexer2 = RegistryIndexer(index_dir=index_dir)
        indexer2.load()
        assert indexer2.is_loaded

    def test_reload_produces_same_doc_count(self, registry, index_dir):
        indexer = RegistryIndexer(index_dir=index_dir)
        indexer.build(registry)
        count1 = indexer.doc_count

        indexer2 = RegistryIndexer(index_dir=index_dir)
        indexer2.load()
        assert indexer2.doc_count == count1

    def test_build_then_load_does_not_require_registry(self, registry, index_dir):
        indexer = RegistryIndexer(index_dir=index_dir)
        indexer.build(registry)

        indexer2 = RegistryIndexer(index_dir=index_dir)
        indexer2.load()  # No registry needed
        assert indexer2.is_loaded


class TestFeatureFlag:
    """FF_RETRIEVER controls retriever availability."""

    def test_flag_off_build_still_works(self, registry, index_dir):
        # Building is always allowed; the flag gates retrieval (in later slices)
        indexer = RegistryIndexer(index_dir=index_dir)
        indexer.build(registry)
        assert indexer.is_loaded
