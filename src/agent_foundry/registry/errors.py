"""Typed exceptions for capability registry operations."""

from pathlib import Path


class CapabilitySpecValidationError(Exception):
    """Raised when a capability spec fails Pydantic validation."""

    def __init__(
        self,
        message: str,
        file_path: Path,
        missing_fields: list[str] | None = None,
    ):
        self.file_path = file_path
        self.missing_fields = missing_fields or []
        super().__init__(message)


class CapabilitySpecParseError(Exception):
    """Raised when a capability spec file cannot be parsed."""

    def __init__(
        self,
        message: str,
        file_path: Path,
        line: int | None = None,
        column: int | None = None,
    ):
        self.file_path = file_path
        self.line = line
        self.column = column
        super().__init__(message)
