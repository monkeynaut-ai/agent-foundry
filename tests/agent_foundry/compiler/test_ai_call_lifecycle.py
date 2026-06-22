"""AICall emits lifecycle events, and both AICall and FunctionAction
events carry the construct's ``name`` alongside the positional node_id.

Before this, AICalls were invisible in lifecycle.jsonl (no AI_CALL_* event
types existed) and FunctionAction events were keyed only by the positional
node_id, so a reviewer failure showed up as "root_step_2_body_step_3" — or
not at all.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.ai_models.inference import (
    InferenceParameters,
    InferenceProvider,
    InferenceRequest,
    InferenceResult,
)
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.compiler.compiler import compile_process
from agent_foundry.constructs.ai_call import AICall, ModelInput
from agent_foundry.constructs.models import FunctionAction
from agent_foundry.constructs.process import Process
from agent_foundry.models.usage import TokenUsage
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.lifecycle_writer import LifecycleWriter
from agent_foundry.orchestration.run_context import RunContext, current_run_context


class _Input(BaseModel):
    text: str


class _Output(BaseModel):
    result: str


class _CapturingWriter(LifecycleWriter):
    def __init__(self) -> None:
        self.events: list[tuple[LifecycleEvent, dict[str, Any]]] = []

    def append(self, event_type: LifecycleEvent, **fields: Any) -> None:
        self.events.append((event_type, fields))

    def append_run_event(self, kind: str, **fields: Any) -> None:
        self.events.append((LifecycleEvent.DOMAIN, {"kind": kind, **fields}))

    def close(self) -> None:
        return None

    def fields_for(self, event_type: LifecycleEvent) -> dict[str, Any]:
        return next(f for t, f in self.events if t == event_type)

    def types(self) -> list[LifecycleEvent]:
        return [t for t, _ in self.events]


class _OkProvider(InferenceProvider):
    def __init__(self, usage: TokenUsage | None = None) -> None:
        self._usage = usage

    async def __call__(self, request: InferenceRequest) -> InferenceResult:
        return InferenceResult(output=_Output(result="ok"), usage=self._usage)

    async def close(self) -> None:
        return None


class _RaisingProvider(InferenceProvider):
    async def __call__(self, request: InferenceRequest) -> InferenceResult:
        raise ValueError("boom")

    async def close(self) -> None:
        return None


def _entry(provider: InferenceProvider) -> ModelEntry:
    return ModelEntry(
        model_id="fake",
        provider=provider,
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )


def _ai_call(*, name: str | None = None, provider: InferenceProvider | None = None) -> AICall:
    return AICall[_Input, _Output](
        model_input=ModelInput[_Input](instructions="s", prompt="p"),
        parameters=InferenceParameters(max_tokens=16),
        model=_entry(provider or _OkProvider()),
        name=name,
    )


@pytest.fixture
def writer(tmp_path: Any) -> Any:
    w = _CapturingWriter()
    ctx = RunContext(
        run_id="lc-test",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=w,
        cancel_event=asyncio.Event(),
        env={},
    )
    token = current_run_context.set(ctx)
    yield w
    current_run_context.reset(token)


def test_ai_call_emits_started_and_completed_with_name(writer: _CapturingWriter) -> None:
    graph = compile_process(Process(_ai_call(name="design_correctness_review")))
    asyncio.run(graph.ainvoke({"text": "x"}))

    assert LifecycleEvent.AI_CALL_STARTED in writer.types()
    assert LifecycleEvent.AI_CALL_COMPLETED in writer.types()
    started = writer.fields_for(LifecycleEvent.AI_CALL_STARTED)
    assert started["name"] == "design_correctness_review"
    assert started["node_id"] == "root"


def test_ai_call_completed_carries_token_usage(writer: _CapturingWriter) -> None:
    provider = _OkProvider(usage=TokenUsage(input_tokens=30, output_tokens=12))
    graph = compile_process(Process(_ai_call(provider=provider)))
    asyncio.run(graph.ainvoke({"text": "x"}))

    completed = writer.fields_for(LifecycleEvent.AI_CALL_COMPLETED)
    assert completed["usage"]["input_tokens"] == 30
    assert completed["usage"]["output_tokens"] == 12
    assert completed["num_turns"] == 1
    # No USD figure on the AICall path in v1.
    assert "total_cost_usd" not in completed


def test_ai_call_completed_omits_usage_when_provider_reports_none(
    writer: _CapturingWriter,
) -> None:
    graph = compile_process(Process(_ai_call(provider=_OkProvider())))
    asyncio.run(graph.ainvoke({"text": "x"}))

    completed = writer.fields_for(LifecycleEvent.AI_CALL_COMPLETED)
    assert "usage" not in completed
    assert "num_turns" not in completed


def test_ai_call_emits_failed_on_provider_error(writer: _CapturingWriter) -> None:
    graph = compile_process(Process(_ai_call(name="rev", provider=_RaisingProvider())))
    with pytest.raises(ValueError):
        asyncio.run(graph.ainvoke({"text": "x"}))

    assert LifecycleEvent.AI_CALL_COMPLETED not in writer.types()
    failed = writer.fields_for(LifecycleEvent.AI_CALL_FAILED)
    assert failed["name"] == "rev"
    assert "boom" in failed["reason"]


def test_ai_call_name_falls_back_to_node_id(writer: _CapturingWriter) -> None:
    graph = compile_process(Process(_ai_call(name=None)))
    asyncio.run(graph.ainvoke({"text": "x"}))

    started = writer.fields_for(LifecycleEvent.AI_CALL_STARTED)
    assert started["name"] == "root"


def test_function_action_event_carries_name(writer: _CapturingWriter) -> None:
    fa = FunctionAction[_Input, _Output](
        function=lambda s: _Output(result="y"), name="aggregate_design_verdict"
    )
    graph = compile_process(Process(fa))
    asyncio.run(graph.ainvoke({"text": "x"}))

    started = writer.fields_for(LifecycleEvent.FUNCTION_ACTION_STARTED)
    assert started["name"] == "aggregate_design_verdict"
    assert started["node_id"] == "root"
