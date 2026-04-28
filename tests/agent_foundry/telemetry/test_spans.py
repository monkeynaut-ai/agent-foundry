"""Tests for emit_span using OTel's InMemorySpanExporter.

Tests construct a RunContext with a TracerProvider anchored on it and set
the ``current_run_context`` ContextVar — emit_span resolves the provider
from the context, so no process-global state is touched.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace.status import StatusCode
from pydantic import BaseModel

from agent_foundry.orchestration.run_context import (
    NoOpLifecycleWriter,
    RunContext,
    current_run_context,
)
from agent_foundry.telemetry import attributes
from agent_foundry.telemetry.spans import emit_span


class _In(BaseModel):
    ticket_id: str


class _Out(BaseModel):
    success: bool


@pytest.fixture()
def in_memory_exporter(tmp_path: Path) -> Iterator[InMemorySpanExporter]:
    """Build a TracerProvider with an InMemorySpanExporter, anchor it on a
    RunContext, and set the ContextVar. emit_span resolves the provider
    from the context — nothing is set on the OTel global tracer-provider
    state.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    ctx = RunContext(
        run_id="test-spans",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        telemetry_provider=provider,
    )
    token = current_run_context.set(ctx)
    try:
        yield exporter
    finally:
        current_run_context.reset(token)
        provider.shutdown()


def test_emit_span_emits_one_span_with_input_and_output(
    in_memory_exporter: InMemorySpanExporter,
) -> None:
    in_memory_exporter.clear()
    with emit_span(
        name="agent_foundry.AgentAction",
        primitive_type="AgentAction",
        primitive_name="reviewer",
        input_model=_In(ticket_id="42"),
        run_id="run-1",
        redaction=None,
    ) as handle:
        handle.set_output(_Out(success=True))

    spans = in_memory_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "agent_foundry.AgentAction"
    assert span.attributes is not None
    assert span.attributes[attributes.AF_PRIMITIVE_TYPE] == "AgentAction"
    assert span.attributes[attributes.AF_PRIMITIVE_NAME] == "reviewer"
    assert span.attributes[attributes.AF_RUN_ID] == "run-1"
    assert "ticket_id" in str(span.attributes[attributes.AF_INPUT])
    assert "success" in str(span.attributes[attributes.AF_OUTPUT])
    assert span.status.status_code == StatusCode.OK


def test_emit_span_records_exception_and_sets_error_status(
    in_memory_exporter: InMemorySpanExporter,
) -> None:
    in_memory_exporter.clear()
    with (
        pytest.raises(RuntimeError, match="boom"),
        emit_span(
            name="agent_foundry.AgentAction",
            primitive_type="AgentAction",
            primitive_name=None,
            input_model=_In(ticket_id="42"),
            run_id=None,
            redaction=None,
        ),
    ):
        raise RuntimeError("boom")

    spans = in_memory_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert any(event.name == "exception" for event in span.events)


def test_emit_span_omits_run_id_attribute_when_none(
    in_memory_exporter: InMemorySpanExporter,
) -> None:
    in_memory_exporter.clear()
    with emit_span(
        name="agent_foundry.AgentAction",
        primitive_type="AgentAction",
        primitive_name=None,
        input_model=_In(ticket_id="42"),
        run_id=None,
        redaction=None,
    ) as handle:
        handle.set_output(_Out(success=True))

    span = in_memory_exporter.get_finished_spans()[0]
    assert span.attributes is not None
    assert attributes.AF_RUN_ID not in span.attributes


def test_emit_span_set_token_usage_writes_gen_ai_attributes(
    in_memory_exporter: InMemorySpanExporter,
) -> None:
    in_memory_exporter.clear()
    with emit_span(
        name="agent_foundry.AgentAction",
        primitive_type="AgentAction",
        primitive_name=None,
        input_model=_In(ticket_id="42"),
        run_id=None,
        redaction=None,
    ) as handle:
        handle.set_output(_Out(success=True))
        handle.set_model_id("claude-opus-4-7")
        handle.set_token_usage(input_tokens=120, output_tokens=85)

    span = in_memory_exporter.get_finished_spans()[0]
    assert span.attributes is not None
    assert span.attributes[attributes.GEN_AI_REQUEST_MODEL] == "claude-opus-4-7"
    assert span.attributes[attributes.GEN_AI_USAGE_INPUT_TOKENS] == 120
    assert span.attributes[attributes.GEN_AI_USAGE_OUTPUT_TOKENS] == 85


def test_emit_span_is_noop_when_no_run_context_active() -> None:
    """No active RunContext → no provider → emit_span yields a no-op handle.

    The body still runs and exceptions still propagate, but no span emerges
    and the handle's setters are no-ops. This is the path for callers who
    run without telemetry configured (telemetry=None on run_primitive_plan).
    """
    with emit_span(
        name="x",
        primitive_type="X",
        primitive_name=None,
        input_model=_In(ticket_id="1"),
        run_id=None,
        redaction=None,
    ) as handle:
        handle.set_output(_Out(success=True))
        handle.set_model_id("claude")
        handle.set_token_usage(input_tokens=1, output_tokens=1)


def test_emit_span_is_noop_when_run_context_has_no_provider(tmp_path: Path) -> None:
    """RunContext active but telemetry_provider is None → no-op."""
    ctx = RunContext(
        run_id="no-prov",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        telemetry_provider=None,
    )
    token = current_run_context.set(ctx)
    try:
        with emit_span(
            name="x",
            primitive_type="X",
            primitive_name=None,
            input_model=_In(ticket_id="1"),
            run_id=None,
            redaction=None,
        ) as handle:
            handle.set_output(_Out(success=True))
    finally:
        current_run_context.reset(token)


def test_emit_span_noop_propagates_exception_when_no_provider() -> None:
    """No active provider must not silently swallow exceptions raised in
    the body. Telemetry is independent of error propagation."""
    with (
        pytest.raises(RuntimeError, match="boom"),
        emit_span(
            name="x",
            primitive_type="X",
            primitive_name=None,
            input_model=_In(ticket_id="1"),
            run_id=None,
            redaction=None,
        ),
    ):
        raise RuntimeError("boom")
