"""Typed exceptions for retriever operations."""

from pathlib import Path


class IndexLoadError(Exception):
    """Raised when the persisted index cannot be loaded."""

    def __init__(self, message: str, index_path: Path):
        self.index_path = index_path
        super().__init__(message)


class RetrieverUnavailableError(Exception):
    """Raised when the retriever backend is unavailable."""

    def __init__(self, message: str):
        super().__init__(message)
