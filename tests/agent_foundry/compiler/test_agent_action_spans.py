"""Tests for OTel span emission around AgentAction execution.

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

from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy
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


def _build_action(executor) -> AgentAction[_In, _Out]:
    return AgentAction[_In, _Out](
        name="reviewer",
        prompt_builder=lambda inp: f"prompt:{inp.ticket_id}",
        instructions_provider=lambda _: "instructions",
        executor=executor,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    )


def test_agent_action_emits_one_span_per_invocation(
    exporter_and_provider: tuple[InMemorySpanExporter, TracerProvider],
    tmp_path: Path,
) -> None:
    from agent_foundry.compiler.primitive_compiler import _compile_primitive
    from agent_foundry.orchestration.run_context import (
        NoOpLifecycleWriter,
        RunContext,
        current_run_context,
    )

    exporter, provider = exporter_and_provider

    def fake_executor(*, primitive, prompt, instructions, run_ctx) -> _Out:
        return _Out(success=True)

    action = _build_action(fake_executor)
    plan = PrimitivePlan(root=action)

    ctx = RunContext(
        run_id="run-spans",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        telemetry_provider=provider,
    )
    tok = current_run_context.set(ctx)
    try:
        graph = _compile_primitive(plan)
        graph.invoke(_In(ticket_id="42").model_dump())
    finally:
        current_run_context.reset(tok)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes is not None
    assert span.attributes[attributes.AF_PRIMITIVE_TYPE] == "AgentAction"
    assert span.attributes[attributes.AF_PRIMITIVE_NAME] == "reviewer"
    assert span.attributes[attributes.AF_RUN_ID] == "run-spans"
    assert span.attributes["gen_ai.operation.name"] == "chat"
    assert "ticket_id" in str(span.attributes[attributes.AF_INPUT])
    assert "success" in str(span.attributes[attributes.AF_OUTPUT])
    assert span.status.status_code == StatusCode.OK


def test_agent_action_executor_exception_records_error_span(
    exporter_and_provider: tuple[InMemorySpanExporter, TracerProvider],
    tmp_path: Path,
) -> None:
    from agent_foundry.compiler.primitive_compiler import _compile_primitive
    from agent_foundry.orchestration.run_context import (
        NoOpLifecycleWriter,
        RunContext,
        current_run_context,
    )

    exporter, provider = exporter_and_provider

    def boom_executor(*, primitive, prompt, instructions, run_ctx) -> _Out:
        raise RuntimeError("executor blew up")

    action = _build_action(boom_executor)
    plan = PrimitivePlan(root=action)

    ctx = RunContext(
        run_id="run-fail",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        telemetry_provider=provider,
    )
    tok = current_run_context.set(ctx)
    try:
        graph = _compile_primitive(plan)
        with pytest.raises(RuntimeError, match="executor blew up"):
            graph.invoke(_In(ticket_id="42").model_dump())
    finally:
        current_run_context.reset(tok)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].status.status_code == StatusCode.ERROR
