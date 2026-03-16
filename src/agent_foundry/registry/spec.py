"""Role spec schema and file loader."""

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from agent_foundry.registry.errors import (
    RoleSpecParseError,
    RoleSpecValidationError,
)


class ImplementationPointer(BaseModel):
    """Reference to the Python class that implements a role."""

    module: str
    class_name: str
    method: str = "__call__"


class QualityControls(BaseModel):
    """Per-role quality control settings."""

    timeout_seconds: int = Field(default=30, ge=1)
    max_retries: int = Field(default=0, ge=0)


class RoleSpec(BaseModel):
    """Schema for a single role specification."""

    name: str
    description: str
    version: str
    implementation: ImplementationPointer
    inputs_schema: dict[str, Any]
    outputs_schema: dict[str, Any]
    tags: list[str] = Field(default_factory=list)
    quality_controls: QualityControls = Field(default_factory=QualityControls)


def load_role_spec(path: Path) -> RoleSpec:
    """Load and validate a role spec from a YAML or JSON file.

    Args:
        path: Path to a .yaml, .yml, or .json role spec file.

    Returns:
        A validated RoleSpec instance.

    Raises:
        RoleSpecParseError: If the file cannot be read or parsed.
        RoleSpecValidationError: If the parsed data fails schema validation.
    """
    path = Path(path)

    try:
        text = path.read_text()
    except OSError as e:
        raise RoleSpecParseError(
            message=f"Cannot read file {path}: {e}",
            file_path=path,
        ) from e

    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        data = _parse_yaml(text, path)
    elif suffix == ".json":
        data = _parse_json(text, path)
    else:
        raise RoleSpecParseError(
            message=f"Unsupported file extension: {suffix}. Use .yaml, .yml, or .json",
            file_path=path,
        )

    return _validate_spec(data, path)


def _parse_yaml(text: str, path: Path) -> dict:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        line = column = None
        mark = getattr(e, "problem_mark", None)
        if mark is not None:
            line = mark.line + 1
            column = mark.column + 1
        raise RoleSpecParseError(
            message=f"YAML parse error in {path}: {e}",
            file_path=path,
            line=line,
            column=column,
        ) from e
    if not isinstance(data, dict):
        raise RoleSpecParseError(
            message=f"Expected a mapping in {path}, got {type(data).__name__}",
            file_path=path,
        )
    return data


def _parse_json(text: str, path: Path) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RoleSpecParseError(
            message=f"JSON parse error in {path}: {e}",
            file_path=path,
            line=e.lineno,
            column=e.colno,
        ) from e
    if not isinstance(data, dict):
        raise RoleSpecParseError(
            message=f"Expected a mapping in {path}, got {type(data).__name__}",
            file_path=path,
        )
    return data


def _validate_spec(data: dict, path: Path) -> RoleSpec:
    try:
        return RoleSpec(**data)
    except ValidationError as e:
        missing = [
            str(err["loc"][0])
            for err in e.errors()
            if err["type"] == "missing" and len(err["loc"]) > 0
        ]
        raise RoleSpecValidationError(
            message=f"Validation error in {path}: {e}",
            file_path=path,
            missing_fields=missing,
        ) from e
