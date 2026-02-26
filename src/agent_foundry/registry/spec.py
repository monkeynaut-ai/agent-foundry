"""Capability spec schema and file loader."""

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ImplementationPointer(BaseModel):
    """Reference to the Python class that implements a capability."""

    module: str
    class_name: str


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
        ValueError: If the file extension is not supported.
    """
    path = Path(path)
    text = path.read_text()

    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        raise ValueError(f"Unsupported file extension: {suffix}. Use .yaml, .yml, or .json")

    return CapabilitySpec(**data)
