"""Tests for RedactionPolicy applied to emit_span."""

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

from agent_foundry.orchestration.run_context import (
    NoOpLifecycleWriter,
    RunContext,
    current_run_context,
)
from agent_foundry.telemetry import attributes
from agent_foundry.telemetry.config import RedactionPolicy
from agent_foundry.telemetry.spans import emit_span


class _Sensitive(BaseModel):
    ticket_id: str
    api_key: str


@pytest.fixture()
def exporter(tmp_path: Path) -> Iterator[InMemorySpanExporter]:
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    ctx = RunContext(
        run_id="test-redaction",
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
        yield exp
    finally:
        current_run_context.reset(token)
        provider.shutdown()


def test_redact_input_replaces_sensitive_field_in_span_attribute(
    exporter: InMemorySpanExporter,
) -> None:
    exporter.clear()
    policy = RedactionPolicy(
        redact_input=lambda m: _Sensitive(ticket_id=m.ticket_id, api_key="[REDACTED]"),
    )

    with emit_span(
        name="primitive",
        primitive_type="X",
        primitive_name=None,
        input_model=_Sensitive(ticket_id="1", api_key="sk-real"),
        run_id=None,
        redaction=policy,
    ) as handle:
        handle.set_output(_Sensitive(ticket_id="1", api_key="sk-real"))

    span = exporter.get_finished_spans()[0]
    assert span.attributes is not None
    payload = json.loads(str(span.attributes[attributes.AF_INPUT]))
    assert payload["api_key"] == "[REDACTED]"
    assert payload["ticket_id"] == "1"


def test_redact_output_replaces_sensitive_field_in_span_attribute(
    exporter: InMemorySpanExporter,
) -> None:
    exporter.clear()
    policy = RedactionPolicy(
        redact_output=lambda m: _Sensitive(ticket_id=m.ticket_id, api_key="[REDACTED]"),
    )

    with emit_span(
        name="primitive",
        primitive_type="X",
        primitive_name=None,
        input_model=_Sensitive(ticket_id="1", api_key="sk-real"),
        run_id=None,
        redaction=policy,
    ) as handle:
        handle.set_output(_Sensitive(ticket_id="1", api_key="sk-real"))

    span = exporter.get_finished_spans()[0]
    assert span.attributes is not None
    payload = json.loads(str(span.attributes[attributes.AF_OUTPUT]))
    assert payload["api_key"] == "[REDACTED]"


def test_redact_input_returning_non_basemodel_raises(
    exporter: InMemorySpanExporter,
) -> None:
    exporter.clear()
    policy = RedactionPolicy(
        redact_input=lambda m: {"not": "a basemodel"},  # type: ignore[return-value,arg-type]
    )

    with (
        pytest.raises(TypeError, match="redact_input must return a Pydantic BaseModel"),
        emit_span(
            name="primitive",
            primitive_type="X",
            primitive_name=None,
            input_model=_Sensitive(ticket_id="1", api_key="sk"),
            run_id=None,
            redaction=policy,
        ),
    ):
        pass


def test_no_redaction_policy_passes_input_through_unchanged(
    exporter: InMemorySpanExporter,
) -> None:
    exporter.clear()
    with emit_span(
        name="primitive",
        primitive_type="X",
        primitive_name=None,
        input_model=_Sensitive(ticket_id="1", api_key="sk-real"),
        run_id=None,
        redaction=None,
    ) as handle:
        handle.set_output(_Sensitive(ticket_id="1", api_key="sk-real"))

    span = exporter.get_finished_spans()[0]
    assert span.attributes is not None
    payload = json.loads(str(span.attributes[attributes.AF_INPUT]))
    assert payload["api_key"] == "sk-real"
