"""Typed exceptions for role registry operations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_foundry.registry.spec import ImplementationPointer


class RoleSpecValidationError(Exception):
    """Raised when a role spec fails Pydantic validation."""

    def __init__(
        self,
        message: str,
        file_path: Path,
        missing_fields: list[str] | None = None,
    ):
        self.file_path = file_path
        self.missing_fields = missing_fields or []
        super().__init__(message)


class DuplicateRoleError(Exception):
    """Raised when two specs share the same role name."""

    def __init__(
        self,
        message: str,
        role_name: str,
        file_paths: list[Path],
    ):
        self.role_name = role_name
        self.file_paths = file_paths
        super().__init__(message)


class RoleImportError(Exception):
    """Raised when a role implementation cannot be imported."""

    def __init__(
        self,
        message: str,
        pointer: ImplementationPointer,
    ):
        self.pointer = pointer
        super().__init__(message)


class RoleExecutionError(Exception):
    """Raised when role execution fails due to input/output validation or runtime error."""

    def __init__(
        self,
        message: str,
        role_name: str,
        phase: str,
        field_paths: list[str] | None = None,
    ):
        self.role_name = role_name
        self.phase = phase
        self.field_paths = field_paths or []
        super().__init__(message)


class RoleSpecParseError(Exception):
    """Raised when a role spec file cannot be parsed."""

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
