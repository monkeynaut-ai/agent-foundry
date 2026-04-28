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
from agent_foundry.telemetry.setup import build_tracer_provider
from agent_foundry.telemetry.spans import SpanHandle, emit_span

__all__ = [
    "ArtifactSpec",
    "RedactionPolicy",
    "RunDefinition",
    "RunStats",
    "SpanHandle",
    "TelemetryConfig",
    "attributes",
    "build_tracer_provider",
    "emit_span",
]
