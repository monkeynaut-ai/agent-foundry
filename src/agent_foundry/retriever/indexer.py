"""Registry indexer: builds and persists a FAISS index from capability specs and docs."""

import hashlib
import json
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from agent_foundry.registry.registry import CapabilityRegistry

FF_RETRIEVER = False

# Metadata file to track index state
_META_FILE = "index_meta.json"


class DeterministicEmbeddings(Embeddings):
    """Hash-based embeddings for deterministic, offline indexing."""

    def __init__(self, dim: int = 64):
        self._dim = dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._hash_embed(text)

    def _hash_embed(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        raw = [b / 255.0 for b in h]
        # Pad or truncate to dim
        vec = (raw * (self._dim // len(raw) + 1))[:self._dim]
        return vec


class RegistryIndexer:
    """Builds, persists, and loads a FAISS vector index from registry specs."""

    def __init__(
        self,
        index_dir: Path,
        embeddings: Embeddings | None = None,
    ):
        self._index_dir = Path(index_dir)
        self._embeddings = embeddings or DeterministicEmbeddings()
        self._store: FAISS | None = None
        self._doc_count: int = 0

    @property
    def is_loaded(self) -> bool:
        return self._store is not None

    @property
    def doc_count(self) -> int:
        return self._doc_count

    def build(
        self,
        registry: CapabilityRegistry,
        docs_dir: Path | None = None,
    ) -> None:
        """Ingest registry specs and optional docs, build and persist index."""
        documents = self._specs_to_documents(registry)

        if docs_dir is not None:
            documents.extend(self._docs_to_documents(docs_dir))

        if not documents:
            documents = [Document(page_content="empty", metadata={"source": "empty"})]

        self._store = FAISS.from_documents(documents, self._embeddings)
        self._doc_count = len(documents)

        self._index_dir.mkdir(parents=True, exist_ok=True)
        self._store.save_local(str(self._index_dir))

        meta = {"doc_count": self._doc_count}
        (self._index_dir / _META_FILE).write_text(json.dumps(meta))

    def load(self) -> None:
        """Load a previously persisted index."""
        self._store = FAISS.load_local(
            str(self._index_dir),
            self._embeddings,
            allow_dangerous_deserialization=True,
        )
        meta_path = self._index_dir / _META_FILE
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            self._doc_count = meta.get("doc_count", 0)

    def _specs_to_documents(self, registry: CapabilityRegistry) -> list[Document]:
        docs = []
        for name in sorted(registry.names()):
            spec = registry.get(name)
            if spec is None:
                continue
            content = (
                f"Capability: {spec.name}\n"
                f"Description: {spec.description}\n"
                f"Version: {spec.version}\n"
                f"Tags: {', '.join(spec.tags)}\n"
                f"Module: {spec.implementation.module}\n"
                f"Class: {spec.implementation.class_name}\n"
            )
            chunk_id = hashlib.sha256(f"spec:{spec.name}".encode()).hexdigest()[:16]
            docs.append(Document(
                page_content=content,
                metadata={
                    "source": f"registry:{spec.name}",
                    "chunk_id": chunk_id,
                    "type": "capability_spec",
                },
            ))
        return docs

    def _docs_to_documents(self, docs_dir: Path) -> list[Document]:
        docs = []
        for path in sorted(docs_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in (".md", ".txt", ".rst"):
                continue
            text = path.read_text()
            chunk_id = hashlib.sha256(f"doc:{path.name}".encode()).hexdigest()[:16]
            docs.append(Document(
                page_content=text,
                metadata={
                    "source": f"docs:{path.name}",
                    "chunk_id": chunk_id,
                    "type": "curated_doc",
                },
            ))
        return docs
