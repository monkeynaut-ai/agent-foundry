"""Tests for OTel span emission around AICall execution.

Per-test isolation: each test builds its own TracerProvider, anchors it on
a RunContext, and sets the ``current_run_context`` ContextVar. emit_span
resolves the provider from the context — no global state is touched.
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

from agent_foundry.ai_models.inference import (
    InferenceParameters,
    InferenceProvider,
    InferenceRequest,
)
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.primitives.ai_call import AICall, ModelInput
from agent_foundry.primitives.plan import PrimitivePlan
from agent_foundry.telemetry import attributes


class _In(BaseModel):
    ticket_id: str


class _Out(BaseModel):
    success: bool


@pytest.fixture()
def exporter_and_provider() -> Iterator[tuple[InMemorySpanExporter, TracerProvider]]:
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    yield exp, provider
    provider.shutdown()


def _build_action(provider: InferenceProvider) -> AICall[_In, _Out]:
    return AICall[_In, _Out](
        model_input=ModelInput[_In](
            instructions="you are a reviewer",
            prompt=lambda s: f"review ticket {s.ticket_id}",
        ),
        parameters=InferenceParameters(max_tokens=256),
        model=ModelEntry(
            model_id="fake",
            provider=provider,
            capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
        ),
    )


def _run_ctx(tmp_path: Path, provider: TracerProvider):
    from agent_foundry.orchestration.run_context import NoOpLifecycleWriter, RunContext

    return RunContext(
        run_id="run-spans",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        telemetry_provider=provider,
    )


def test_ai_call_emits_one_span_per_invocation(
    exporter_and_provider: tuple[InMemorySpanExporter, TracerProvider],
    tmp_path: Path,
) -> None:
    from agent_foundry.compiler.primitive_compiler import compile_runtime_plan
    from agent_foundry.orchestration.run_context import current_run_context

    exporter, provider = exporter_and_provider

    class _FakeProvider(InferenceProvider):
        async def __call__(self, request: InferenceRequest) -> BaseModel:
            return _Out(success=True)

        async def close(self) -> None:
            pass

    action = _build_action(_FakeProvider())
    plan = PrimitivePlan(root=action)

    ctx = _run_ctx(tmp_path, provider)
    tok = current_run_context.set(ctx)
    try:
        graph = compile_runtime_plan(plan)
        asyncio.run(graph.ainvoke(_In(ticket_id="42").model_dump()))
    finally:
        current_run_context.reset(tok)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes is not None
    assert span.attributes[attributes.AF_PRIMITIVE_TYPE] == "AICall"
    assert span.attributes[attributes.AF_RUN_ID] == "run-spans"
    assert span.attributes["gen_ai.operation.name"] == "chat"
    assert "ticket_id" in str(span.attributes[attributes.AF_INPUT])
    assert "success" in str(span.attributes[attributes.AF_OUTPUT])
    assert span.status.status_code == StatusCode.OK


def test_ai_call_provider_exception_records_error_span(
    exporter_and_provider: tuple[InMemorySpanExporter, TracerProvider],
    tmp_path: Path,
) -> None:
    from agent_foundry.compiler.primitive_compiler import compile_runtime_plan
    from agent_foundry.orchestration.run_context import current_run_context

    exporter, provider = exporter_and_provider

    class _BoomProvider(InferenceProvider):
        async def __call__(self, request: InferenceRequest) -> BaseModel:
            raise RuntimeError("provider blew up")

        async def close(self) -> None:
            pass

    action = _build_action(_BoomProvider())
    plan = PrimitivePlan(root=action)

    ctx = _run_ctx(tmp_path, provider)
    tok = current_run_context.set(ctx)
    try:
        graph = compile_runtime_plan(plan)
        with pytest.raises(RuntimeError, match="provider blew up"):
            asyncio.run(graph.ainvoke(_In(ticket_id="42").model_dump()))
    finally:
        current_run_context.reset(tok)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].status.status_code == StatusCode.ERROR
