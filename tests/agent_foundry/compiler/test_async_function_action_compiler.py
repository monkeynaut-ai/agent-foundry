"""AsyncFunctionAction compiles to an async node that runs on the event loop,
merges typed output into accumulated state, supports arity-0 callables, and
emits FUNCTION_ACTION_* lifecycle events on success and failure.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry import runtime
from agent_foundry.compiler.compiler import compile_process
from agent_foundry.constructs.models import AsyncFunctionAction
from agent_foundry.constructs.process import Process
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.lifecycle_writer import LifecycleWriter, NoOpLifecycleWriter
from agent_foundry.orchestration.run_context import RunContext, current_run_context
from agent_foundry.responders.models import (
    ClarificationRequest,
    ResponderContext,
    ResponderRequest,
    ResponderResponse,
)
from agent_foundry.responders.protocol import Responder, static_provider


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


@pytest.fixture
def writer(tmp_path: Any) -> Any:
    w = _CapturingWriter()
    ctx = RunContext(
        run_id="afa-test",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=None,
        lifecycle_writer=w,
        cancel_event=asyncio.Event(),
        env={},
    )
    token = current_run_context.set(ctx)
    yield w
    current_run_context.reset(token)


def test_async_function_action_runs_and_merges_output(writer: _CapturingWriter) -> None:
    async def fn(state: _Input) -> _Output:
        return _Output(result=state.text.upper())

    action = AsyncFunctionAction[_Input, _Output](function=fn)
    graph = compile_process(Process(action))
    final = asyncio.run(graph.ainvoke({"text": "hi"}))

    assert final["result"] == "HI"


def test_async_function_action_arity_zero(writer: _CapturingWriter) -> None:
    async def fn() -> _Output:
        return _Output(result="zero")

    action = AsyncFunctionAction[_Input, _Output](function=fn)
    graph = compile_process(Process(action))
    final = asyncio.run(graph.ainvoke({"text": "ignored"}))

    assert final["result"] == "zero"


def test_async_function_action_emits_started_and_completed(writer: _CapturingWriter) -> None:
    async def fn(state: _Input) -> _Output:
        return _Output(result="ok")

    action = AsyncFunctionAction[_Input, _Output](function=fn, name="resolve_choice")
    graph = compile_process(Process(action))
    asyncio.run(graph.ainvoke({"text": "x"}))

    assert LifecycleEvent.FUNCTION_ACTION_STARTED in writer.types()
    assert LifecycleEvent.FUNCTION_ACTION_COMPLETED in writer.types()
    started = writer.fields_for(LifecycleEvent.FUNCTION_ACTION_STARTED)
    assert started["name"] == "resolve_choice"
    assert started["node_id"] == "root"


def test_async_function_action_emits_failed_on_raise(writer: _CapturingWriter) -> None:
    async def fn(state: _Input) -> _Output:
        raise ValueError("boom")

    action = AsyncFunctionAction[_Input, _Output](function=fn, name="boomer")
    graph = compile_process(Process(action))
    with pytest.raises(ValueError):
        asyncio.run(graph.ainvoke({"text": "x"}))

    assert LifecycleEvent.FUNCTION_ACTION_COMPLETED not in writer.types()
    failed = writer.fields_for(LifecycleEvent.FUNCTION_ACTION_FAILED)
    assert failed["name"] == "boomer"
    assert "boom" in failed["reason"]


def test_async_function_action_can_await_responder(tmp_path: Any) -> None:
    class _EchoResponder(Responder):
        async def respond(
            self, request: ResponderRequest, context: ResponderContext
        ) -> ResponderResponse:
            return ResponderResponse(answer="picked-A")

    async def fn(state: _Input) -> _Output:
        r = runtime.responder()
        assert r is not None
        request = ClarificationRequest(question="pick", agent_name="a", invocation=0, turn=0)
        rctx = ResponderContext(
            run_id="afa-resp", request_id="rid", agent_name="a", invocation=0, turn=0
        )
        resp = await r.respond(request, rctx)
        return _Output(result=resp.answer)

    action = AsyncFunctionAction[_Input, _Output](function=fn)
    graph = compile_process(Process(action))

    ctx = RunContext(
        run_id="afa-resp",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=static_provider(_EchoResponder()),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={},
    )
    token = current_run_context.set(ctx)
    try:
        final = asyncio.run(graph.ainvoke({"text": "x"}))
    finally:
        current_run_context.reset(token)

    assert final["result"] == "picked-A"
