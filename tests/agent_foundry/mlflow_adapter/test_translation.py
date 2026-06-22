"""Tests for MLFLOW_TRANSLATIONS constant and emit-time mirroring."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel

from agent_foundry.mlflow_adapter.translation import MLFLOW_TRANSLATIONS
from agent_foundry.orchestration.run_context import (
    NoOpLifecycleWriter,
    RunContext,
    current_run_context,
)
from agent_foundry.telemetry import attributes
from agent_foundry.telemetry.config import TelemetryConfig
from agent_foundry.telemetry.spans import emit_span


class _M(BaseModel):
    x: int


def test_mlflow_translations_constant_shape() -> None:
    assert MLFLOW_TRANSLATIONS["agent_foundry.input"] == "mlflow.spanInputs"
    assert MLFLOW_TRANSLATIONS["agent_foundry.output"] == "mlflow.spanOutputs"


@pytest.fixture()
def telemetry_ctx(tmp_path: Path) -> Iterator[InMemorySpanExporter]:
    """RunContext with a TracerProvider and the MLflow translation table."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    config = TelemetryConfig(
        otlp_endpoint="http://localhost:5000/v1/traces",
        otlp_headers={},
        service_name="t",
        attribute_translations=MLFLOW_TRANSLATIONS,
    )
    ctx = RunContext(
        run_id="t-translation",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        telemetry=config,
        telemetry_provider=provider,
    )
    tok = current_run_context.set(ctx)
    try:
        yield exporter
    finally:
        current_run_context.reset(tok)
        provider.shutdown()


def test_emit_span_dual_writes_input_and_output_via_mlflow_translations(
    telemetry_ctx: InMemorySpanExporter,
) -> None:
    """Both agent_foundry.* and mlflow.* attributes land on the same span,
    written before span.end() — neither lost to OTel's set-after-end no-op.
    """
    with emit_span(
        name="agent_foundry.X",
        construct_type="X",
        construct_name=None,
        input_model=_M(x=1),
        run_id=None,
        redaction=None,
    ) as handle:
        handle.set_output(_M(x=2))

    span = telemetry_ctx.get_finished_spans()[0]
    assert span.attributes is not None
    assert json.loads(str(span.attributes[attributes.AF_INPUT])) == {"x": 1}
    assert json.loads(str(span.attributes[attributes.AF_OUTPUT])) == {"x": 2}
    assert json.loads(str(span.attributes["mlflow.spanInputs"])) == {"x": 1}
    assert json.loads(str(span.attributes["mlflow.spanOutputs"])) == {"x": 2}


def test_emit_span_without_translations_does_not_set_mlflow_attributes(
    tmp_path: Path,
) -> None:
    """If the product opts out of translation by leaving the table empty,
    AF emits only its own ``agent_foundry.*`` namespace.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    config = TelemetryConfig(
        otlp_endpoint="http://localhost:5000/v1/traces",
        otlp_headers={},
        service_name="t",
    )
    ctx = RunContext(
        run_id="t-no-trans",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        telemetry=config,
        telemetry_provider=provider,
    )
    tok = current_run_context.set(ctx)
    try:
        with emit_span(
            name="x",
            construct_type="X",
            construct_name=None,
            input_model=_M(x=1),
            run_id=None,
            redaction=None,
        ) as handle:
            handle.set_output(_M(x=2))
    finally:
        current_run_context.reset(tok)
        provider.shutdown()

    span = exporter.get_finished_spans()[0]
    assert span.attributes is not None
    assert "mlflow.spanInputs" not in span.attributes
    assert "mlflow.spanOutputs" not in span.attributes
