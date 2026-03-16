"""Retrieval API: query interface over the registry index."""

import logging

from langchain_core.documents import Document

from agent_foundry.retriever.indexer import RegistryIndexer

logger = logging.getLogger(__name__)

FF_RETRIEVER = True

DEFAULT_MAX_SNIPPET_LENGTH = 2000


class RetrievalAPI:
    """High-level retrieval API over a built index."""

    def __init__(
        self,
        indexer: RegistryIndexer,
        max_snippet_length: int = DEFAULT_MAX_SNIPPET_LENGTH,
    ):
        self._indexer = indexer
        self._max_snippet_length = max_snippet_length

    def retrieve(self, query: str, k: int = 3) -> list[Document]:
        """Retrieve top-k snippets for a query.

        Uses vector similarity search with exact-name boosting: if the query
        matches a role name exactly, that document is guaranteed in results.
        Snippets are truncated to max_snippet_length.

        Args:
            query: The search query string.
            k: Maximum number of snippets to return.

        Returns:
            List of Document snippets with metadata.

        Raises:
            RuntimeError: If FF_RETRIEVER is disabled.
        """
        if not FF_RETRIEVER:
            raise RuntimeError("retriever is disabled (FF_RETRIEVER=False)")

        # Check for exact role name match via direct lookup
        exact_match = self._indexer.get_by_source(f"registry:{query}")

        # Get vector similarity results
        candidates = self._indexer.retrieve(query, k=k)

        # Build result list: exact match first, then similarity results
        results: list[Document] = []
        seen_ids: set[str] = set()

        if exact_match is not None:
            chunk_id = exact_match.metadata.get("chunk_id", "")
            results.append(exact_match)
            seen_ids.add(chunk_id)

        for doc in candidates:
            if len(results) >= k:
                break
            chunk_id = doc.metadata.get("chunk_id", "")
            if chunk_id not in seen_ids:
                results.append(doc)
                seen_ids.add(chunk_id)

        if not results:
            logger.info("no_hits", extra={"query": query})

        return [self._truncate_snippet(doc) for doc in results]

    def _truncate_snippet(self, doc: Document) -> Document:
        content = doc.page_content
        if len(content) > self._max_snippet_length:
            content = content[: self._max_snippet_length - 3] + "..."
        return Document(page_content=content, metadata=doc.metadata)
