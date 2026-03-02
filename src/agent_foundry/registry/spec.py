"""Capability spec schema and file loader."""

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from agent_foundry.registry.errors import (
    CapabilitySpecParseError,
    CapabilitySpecValidationError,
)


class ImplementationPointer(BaseModel):
    """Reference to the Python class that implements a capability."""

    module: str
    class_name: str
    method: str = "__call__"


class QualityControls(BaseModel):
    """Per-capability quality control settings."""

    timeout_seconds: int = Field(default=30, ge=1)
    max_retries: int = Field(default=0, ge=0)


class CapabilitySpec(BaseModel):
    """Schema for a single capability specification."""

    name: str
    description: str
    version: str
    implementation: ImplementationPointer
    inputs_schema: dict[str, Any]
    outputs_schema: dict[str, Any]
    tags: list[str] = Field(default_factory=list)
    quality_controls: QualityControls = Field(default_factory=QualityControls)


def load_capability_spec(path: Path) -> CapabilitySpec:
    """Load and validate a capability spec from a YAML or JSON file.

    Args:
        path: Path to a .yaml, .yml, or .json capability spec file.

    Returns:
        A validated CapabilitySpec instance.

    Raises:
        CapabilitySpecParseError: If the file cannot be read or parsed.
        CapabilitySpecValidationError: If the parsed data fails schema validation.
    """
    path = Path(path)

    try:
        text = path.read_text()
    except OSError as e:
        raise CapabilitySpecParseError(
            message=f"Cannot read file {path}: {e}",
            file_path=path,
        ) from e

    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        data = _parse_yaml(text, path)
    elif suffix == ".json":
        data = _parse_json(text, path)
    else:
        raise CapabilitySpecParseError(
            message=f"Unsupported file extension: {suffix}. Use .yaml, .yml, or .json",
            file_path=path,
        )

    return _validate_spec(data, path)


def _parse_yaml(text: str, path: Path) -> dict:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        line = column = None
        if hasattr(e, "problem_mark") and e.problem_mark is not None:
            line = e.problem_mark.line + 1
            column = e.problem_mark.column + 1
        raise CapabilitySpecParseError(
            message=f"YAML parse error in {path}: {e}",
            file_path=path,
            line=line,
            column=column,
        ) from e
    if not isinstance(data, dict):
        raise CapabilitySpecParseError(
            message=f"Expected a mapping in {path}, got {type(data).__name__}",
            file_path=path,
        )
    return data


def _parse_json(text: str, path: Path) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise CapabilitySpecParseError(
            message=f"JSON parse error in {path}: {e}",
            file_path=path,
            line=e.lineno,
            column=e.colno,
        ) from e
    if not isinstance(data, dict):
        raise CapabilitySpecParseError(
            message=f"Expected a mapping in {path}, got {type(data).__name__}",
            file_path=path,
        )
    return data


def _validate_spec(data: dict, path: Path) -> CapabilitySpec:
    try:
        return CapabilitySpec(**data)
    except ValidationError as e:
        missing = [
            err["loc"][0]
            for err in e.errors()
            if err["type"] == "missing"
            and len(err["loc"]) > 0
        ]
        raise CapabilitySpecValidationError(
            message=f"Validation error in {path}: {e}",
            file_path=path,
            missing_fields=missing,
        ) from e
