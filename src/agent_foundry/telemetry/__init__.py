"""Telemetry — OpenTelemetry emission, vendor-neutral.

AF emits OTel spans at primitive boundaries. The ``mlflow_adapter`` (under
the optional ``[mlflow]`` extra) is a separate module that consumes these
spans; the telemetry module never imports MLflow.
"""

from agent_foundry.telemetry import attributes
from agent_foundry.telemetry.config import (
    ArtifactSpec,
    RedactionPolicy,
    RunDefinition,
    RunStats,
    TelemetryConfig,
)

__all__ = [
    "ArtifactSpec",
    "RedactionPolicy",
    "RunDefinition",
    "RunStats",
    "TelemetryConfig",
    "attributes",
]
