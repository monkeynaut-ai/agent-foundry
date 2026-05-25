"""Tests for AICall.executor dispatch -- AC B1-B5.

B6 (eval-path executor respect) is in tests-evals/agent_foundry/evals/test_ai_call_eval_executor.py.
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
)
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.compiler.primitive_compiler import compile_runtime_plan
from agent_foundry.primitives.ai_call import AICall, ModelInput
from agent_foundry.primitives.errors import PrimitiveCompilationError
from agent_foundry.primitives.plan import PrimitivePlan


class _Input(BaseModel):
    text: str


class _Output(BaseModel):
    result: str


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


class _CapturingProvider(InferenceProvider):
    def __init__(self) -> None:
        self.calls: list[InferenceRequest] = []

    async def __call__(self, request: InferenceRequest) -> BaseModel:
        self.calls.append(request)
        return _Output(result="from-provider")

    async def close(self) -> None:
        pass


class _RaisingProvider(InferenceProvider):
    """Always raises ValueError — used to verify executor catch branches."""

    async def __call__(self, request: InferenceRequest) -> BaseModel:
        raise ValueError("provider unavailable")

    async def close(self) -> None:
        pass


def _capturing_entry() -> tuple[ModelEntry, _CapturingProvider]:
    provider = _CapturingProvider()
    entry = ModelEntry(
        model_id="fake",
        provider=provider,
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )
    return entry, provider


def _raising_entry() -> ModelEntry:
    return ModelEntry(
        model_id="fake",
        provider=_RaisingProvider(),
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )


def _make_call(*, executor=None, model_entry: ModelEntry | None = None) -> AICall:
    if model_entry is None:
        model_entry, _ = _capturing_entry()
    return AICall[_Input, _Output](
        model_input=ModelInput[_Input](instructions="sys", prompt="usr"),
        parameters=InferenceParameters(max_tokens=16),
        model=model_entry,
        executor=executor,
    )


# ---------------------------------------------------------------------------
# RunContext fixture (required by compiler nodes)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _run_ctx(tmp_path: Any) -> Any:
    import asyncio

    from agent_foundry.orchestration.run_context import (
        NoOpLifecycleWriter,
        RunContext,
        current_run_context,
    )

    ctx = RunContext(
        run_id="executor-test",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    token = current_run_context.set(ctx)
    yield
    current_run_context.reset(token)


# ---------------------------------------------------------------------------
# B1 — default executor (None) uses invoke_ai_call path unchanged
# ---------------------------------------------------------------------------


class TestDefaultExecutor:
    def test_no_executor_uses_provider(self) -> None:
        """B1: executor=None → invoke_ai_call runs; provider receives InferenceRequest."""
        entry, provider = _capturing_entry()
        call = _make_call(model_entry=entry)
        assert call.executor is None

        graph = compile_runtime_plan(PrimitivePlan(call))
        result = asyncio.run(graph.ainvoke({"text": "hello"}))

        assert len(provider.calls) == 1
        assert result["result"] == "from-provider"


# ---------------------------------------------------------------------------
# B2 — sync executor rejected at compile time
# ---------------------------------------------------------------------------


class TestSyncExecutorRejected:
    def test_sync_executor_raises_at_compile_time(self) -> None:
        """B2: sync executor raises PrimitiveCompilationError at compile_runtime_plan."""

        def my_sync_executor(*, primitive: Any, model_input: Any) -> _Output:  # type: ignore[return]
            return _Output(result="sync")

        call = _make_call(executor=my_sync_executor)  # type: ignore[arg-type]

        with pytest.raises(PrimitiveCompilationError, match="executor must be async"):
            compile_runtime_plan(PrimitivePlan(call))


# ---------------------------------------------------------------------------
# B3 — async custom executor
# ---------------------------------------------------------------------------


class TestAsyncCustomExecutor:
    def test_async_executor_called_with_keyword_args(self) -> None:
        """B3: async executor receives (*, primitive, model_input) and its return value is used."""
        received: list[dict] = []

        async def my_async_executor(*, primitive: Any, model_input: Any) -> _Output:
            received.append({"primitive": primitive, "model_input": model_input})
            return _Output(result="from-async-executor")

        call = _make_call(executor=my_async_executor)
        graph = compile_runtime_plan(PrimitivePlan(call))
        result = asyncio.run(graph.ainvoke({"text": "hi"}))

        assert len(received) == 1
        assert received[0]["primitive"] is call
        assert received[0]["model_input"].text == "hi"
        assert result["result"] == "from-async-executor"

    def test_async_executor_provider_not_called(self) -> None:
        """B3: when executor is set, the underlying provider is bypassed."""
        entry, provider = _capturing_entry()

        async def my_async_executor(*, primitive: Any, model_input: Any) -> _Output:
            return _Output(result="custom")

        call = AICall[_Input, _Output](
            model_input=ModelInput[_Input](instructions="s", prompt="p"),
            parameters=InferenceParameters(max_tokens=16),
            model=entry,
            executor=my_async_executor,
        )
        graph = compile_runtime_plan(PrimitivePlan(call))
        asyncio.run(graph.ainvoke({"text": "x"}))

        assert len(provider.calls) == 0


# ---------------------------------------------------------------------------
# B4 — wrong return type raises PrimitiveCompilationError
# ---------------------------------------------------------------------------


class TestExecutorOutputValidation:
    def test_wrong_type_raises(self) -> None:
        """B4: executor returning wrong type triggers PrimitiveCompilationError."""

        class _Wrong(BaseModel):
            other: str

        async def bad_executor(*, primitive: Any, model_input: Any) -> Any:
            return _Wrong(other="nope")

        call = _make_call(executor=bad_executor)
        graph = compile_runtime_plan(PrimitivePlan(call))

        with pytest.raises(PrimitiveCompilationError):
            asyncio.run(graph.ainvoke({"text": "x"}))


# ---------------------------------------------------------------------------
# B5 — executor catches its own exception; Retry sees normal output
# ---------------------------------------------------------------------------


class TestExecutorCatchesException:
    def test_executor_catches_underlying_exception_returns_synthesized_output(self) -> None:
        """B5: executor that catches inference exception returns synthesized O.
        The exception never reaches the AICall caller.
        """

        async def catching_executor(*, primitive: Any, model_input: Any) -> _Output:
            try:
                # Simulate calling an underlying provider that raises.
                raise ValueError("simulated provider failure")
            except ValueError:
                return _Output(result="fallback")

        call = _make_call(executor=catching_executor)
        graph = compile_runtime_plan(PrimitivePlan(call))
        result = asyncio.run(graph.ainvoke({"text": "x"}))

        assert result["result"] == "fallback"

    def test_executor_wrapping_invoke_ai_call_with_new_param_names(self) -> None:
        """B2/F2: consumer can wrap invoke_ai_call using the documented contract."""
        from agent_foundry.ai_models.execute.invoke import invoke_ai_call

        async def wrapping_executor(*, primitive: Any, model_input: Any) -> _Output:
            # This is the canonical wrap pattern — keyword args match invoke_ai_call's params.
            return await invoke_ai_call(primitive=primitive, model_input=model_input)

        entry, provider = _capturing_entry()
        call = AICall[_Input, _Output](
            model_input=ModelInput[_Input](instructions="s", prompt="p"),
            parameters=InferenceParameters(max_tokens=16),
            model=entry,
            executor=wrapping_executor,
        )
        graph = compile_runtime_plan(PrimitivePlan(call))
        result = asyncio.run(graph.ainvoke({"text": "wrap"}))

        assert len(provider.calls) == 1
        assert result["result"] == "from-provider"
