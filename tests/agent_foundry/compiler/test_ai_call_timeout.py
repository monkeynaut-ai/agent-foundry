"""Tests for AICall.timeout_seconds enforcement (issue #80).

A hung inference call must not block the run forever: the compiler wraps the
executor (default or custom) in a per-call deadline derived from
``AICall.timeout_seconds`` and raises ``ConstructTimeoutError`` when exceeded.
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
from agent_foundry.constructs.errors import ConstructTimeoutError
from agent_foundry.constructs.process import Process
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.lifecycle_writer import NoOpLifecycleWriter


class _Input(BaseModel):
    text: str


class _Output(BaseModel):
    result: str


class _SlowProvider(InferenceProvider):
    """Sleeps longer than any test timeout to exercise the deadline."""

    async def __call__(self, request: InferenceRequest) -> InferenceResult:
        await asyncio.sleep(30)
        return InferenceResult(output=_Output(result="too-late"))

    async def close(self) -> None:
        pass


class _RecordingLifecycleWriter(NoOpLifecycleWriter):
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, event_type: LifecycleEvent, **fields: Any) -> None:
        self.events.append((str(event_type), fields))


def _slow_entry() -> ModelEntry:
    return ModelEntry(
        model_id="fake",
        provider=_SlowProvider(),
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )


def _fast_entry() -> ModelEntry:
    class _FastProvider(InferenceProvider):
        async def __call__(self, request: InferenceRequest) -> InferenceResult:
            return InferenceResult(output=_Output(result="ok"))

        async def close(self) -> None:
            pass

    return ModelEntry(
        model_id="fake",
        provider=_FastProvider(),
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )


def _make_call(
    *, executor: Any = None, model_entry: ModelEntry | None = None, timeout_seconds: int = 30
) -> AICall:
    return AICall[_Input, _Output](
        model_input=ModelInput[_Input](instructions="sys", prompt="usr"),
        parameters=InferenceParameters(max_tokens=16),
        model=model_entry if model_entry is not None else _fast_entry(),
        executor=executor,
        timeout_seconds=timeout_seconds,
    )


@pytest.fixture
def _run_ctx(tmp_path: Any) -> Any:
    from agent_foundry.orchestration.run_context import RunContext, current_run_context

    writer = _RecordingLifecycleWriter()
    ctx = RunContext(
        run_id="timeout-test",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=writer,
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    token = current_run_context.set(ctx)
    yield writer
    current_run_context.reset(token)


class TestDefaultPathTimeout:
    def test_slow_provider_times_out(self, _run_ctx: Any) -> None:
        call = _make_call(model_entry=_slow_entry(), timeout_seconds=1)
        graph = compile_process(Process(call))

        with pytest.raises(ConstructTimeoutError):
            asyncio.run(graph.ainvoke({"text": "x"}))


class TestCustomExecutorTimeout:
    def test_slow_async_executor_times_out_and_emits_failed(self, _run_ctx: Any) -> None:
        async def slow_executor(*, construct: Any, model_input: Any) -> _Output:
            await asyncio.sleep(30)
            return _Output(result="too-late")

        call = _make_call(executor=slow_executor, timeout_seconds=1)
        graph = compile_process(Process(call))

        with pytest.raises(ConstructTimeoutError):
            asyncio.run(graph.ainvoke({"text": "x"}))

        assert any(evt == LifecycleEvent.AI_CALL_FAILED for evt, _ in _run_ctx.events)


class TestWithinTimeout:
    def test_fast_executor_not_affected(self, _run_ctx: Any) -> None:
        async def fast_executor(*, construct: Any, model_input: Any) -> _Output:
            return _Output(result="quick")

        call = _make_call(executor=fast_executor, timeout_seconds=30)
        graph = compile_process(Process(call))

        result = asyncio.run(graph.ainvoke({"text": "x"}))
        assert result["result"] == "quick"
