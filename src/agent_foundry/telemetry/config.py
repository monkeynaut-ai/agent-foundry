"""Pydantic models defining the telemetry surface that products configure."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunStats(BaseModel):
    """Run-level statistics computed at run close, passed to RunDefinition.metrics.

    Field availability for the foundational scope of MLflow tracing integration:

    - ``duration_ms``: live (computed from monotonic clock at run open/close).
    - ``span_count``, ``error_count``, ``total_input_tokens``,
      ``total_output_tokens``: ALL ZERO. These fields will be populated by a
      follow-up task that accumulates per-span stats during the run. Until that
      lands, products should not branch on these fields (e.g. don't write
      ``metrics=lambda out, s: {"err_rate": s.error_count / s.span_count}`` —
      it will divide by zero).

    The fields are kept in the model now so the metrics callable signature is
    stable across the follow-up: products can declare them today, get zeros
    for now, and start receiving real values once span tracking lands.
    """

    model_config = ConfigDict(frozen=True)

    duration_ms: float = 0.0
    span_count: int = 0
    error_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0


class ArtifactSpec(BaseModel):
    """Declares a file to log to the active MLflow run as an artifact."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    path: Path
    """Absolute path on disk. Typically points under ``RunContext.artifacts_dir``."""

    artifact_path: str | None = None
    """Optional sub-path within the run's artifact store. Defaults to None
    (logged at the artifact root)."""


class RedactionPolicy(BaseModel):
    """Per-construct redaction callables applied before serialisation to spans."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    redact_input: Callable[[BaseModel], BaseModel] | None = None
    """If set, applied to the input model before it becomes ``agent_foundry.input``.
    Must return the same model type. Receives a copy."""

    redact_output: Callable[[BaseModel], BaseModel] | None = None
    """If set, applied to the output model before it becomes ``agent_foundry.output``.
    Must return the same model type. Receives a copy."""


class RunDefinition(BaseModel):
    """Product-declared shape of one MLflow run.

    ``name``, ``params``, and ``tags`` callables receive the process's *input*
    model and produce the corresponding MLflow concept at run open.

    ``metrics`` is different — it receives the process's *final output* model
    (or None on the failure path) and a ``RunStats`` summary, and returns the
    metrics to log at run close. The runner passes the actual output through
    ``RunContext.on_close`` to make this work.

    On the failure path, the output is None — products that read fields off
    the output must defensively handle that (return ``{}``, return only
    stats-derived metrics, etc.).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: Callable[[BaseModel], str]
    """Receives the process's input model. Returns the MLflow run name."""

    params: Callable[[BaseModel], dict[str, Any]]
    """Receives the process's input model. Returns params to log at run open
    (logged via ``mlflow.log_params``). Apply ``RedactionPolicy.redact_input``
    before reading sensitive fields."""

    tags: dict[str, str] | Callable[[BaseModel], dict[str, str]]
    """Static dict or callable receiving the process's input model. Tags
    attached to the run at open time."""

    metrics: Callable[[BaseModel | None, RunStats], dict[str, float]]
    """Receives the process's final OUTPUT model (or None on the failure path)
    and a ``RunStats`` summary. Returns metrics to log at run close. Read
    output fields defensively — handle ``out is None`` for failed runs."""

    artifacts: list[ArtifactSpec] = Field(default_factory=list)
    """Files to log to the run as artifacts at run close."""


class TelemetryConfig(BaseModel):
    """Product opt-in to telemetry emission. Construct in app startup, pass to
    ``run_process(..., telemetry=config)``. Absence (``None``) disables
    emission entirely.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    otlp_endpoint: str = Field(min_length=1)
    """OTLP/HTTP endpoint URL, e.g. ``http://localhost:5000/v1/traces`` for
    a local MLflow."""

    otlp_headers: dict[str, str]
    """Headers to attach to OTLP requests, e.g. ``{"x-mlflow-experiment-id": "1"}``."""

    service_name: str = Field(min_length=1)
    """OTel resource ``service.name`` attribute. Identifies the AF product."""

    attribute_translations: dict[str, str] = Field(default_factory=dict)
    """Per-attribute mirror table applied at emit time. When AF sets a
    source attribute (e.g. ``agent_foundry.input``), it also sets the
    translated attribute (e.g. ``mlflow.spanInputs``) with the same value
    atomically — both are written before ``span.end()``, so neither is
    lost to OTel's "set after end is a no-op" rule.

    AF core stays vendor-neutral — this is just a data table. Adapters
    provide suitable defaults; for the MLflow adapter, products typically
    pass ``MLFLOW_TRANSLATIONS`` from ``agent_foundry.mlflow_adapter``.
    """

    redaction: RedactionPolicy | None = None
    run_definition: RunDefinition | None = None
