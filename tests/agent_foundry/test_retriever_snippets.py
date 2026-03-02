"""S2.6 — Snippet limits + source metadata.

Tests: snippet length <= configured max; metadata present with doc id + offsets.
"""

from pathlib import Path

import pytest

from agent_foundry.registry.registry import CapabilityRegistry
from agent_foundry.retriever.indexer import RegistryIndexer
from agent_foundry.retriever.retrieval import RetrievalAPI

CAPABILITIES_DIR = Path(__file__).parent.parent.parent / "capabilities"


@pytest.fixture
def retrieval_api(tmp_path):
    registry = CapabilityRegistry.from_directory(CAPABILITIES_DIR)
    index_dir = tmp_path / "index"
    indexer = RegistryIndexer(index_dir=index_dir)
    indexer.build(registry)
    return RetrievalAPI(indexer=indexer, max_snippet_length=200)


class TestSnippetLimits:
    """Snippet content is truncated to configured max length."""

    def test_snippets_within_max_length(self, retrieval_api):
        snippets = retrieval_api.retrieve("rag_retriever")
        for s in snippets:
            assert len(s.page_content) <= 200

    def test_truncated_snippet_ends_with_ellipsis(self, retrieval_api):
        snippets = retrieval_api.retrieve("rag_retriever")
        for s in snippets:
            if len(s.page_content) == 200:
                assert s.page_content.endswith("...")


class TestSourceMetadata:
    """Each snippet includes doc id and source metadata."""

    def test_snippet_has_chunk_id(self, retrieval_api):
        snippets = retrieval_api.retrieve("rag_retriever")
        for s in snippets:
            assert "chunk_id" in s.metadata
            assert s.metadata["chunk_id"] != ""

    def test_snippet_has_source(self, retrieval_api):
        snippets = retrieval_api.retrieve("rag_retriever")
        for s in snippets:
            assert "source" in s.metadata

    def test_snippet_has_type(self, retrieval_api):
        snippets = retrieval_api.retrieve("rag_retriever")
        for s in snippets:
            assert "type" in s.metadata
