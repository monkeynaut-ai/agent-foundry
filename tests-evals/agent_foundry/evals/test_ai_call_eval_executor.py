"""Tests for AC B6: eval path respects AICall.executor.

build_invoke_ai_call_task must dispatch through AICall.executor when set,
not call invoke_ai_call directly.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.ai_models.inference import InferenceParameters
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.evals.agent_foundry_tasks import build_invoke_ai_call_task
from agent_foundry.primitives.ai_call import AICall, ModelInput


class _Input(BaseModel):
    text: str


class _Output(BaseModel):
    result: str


def _never_called_entry() -> ModelEntry:
    """ModelEntry whose provider raises if called — verifies the executor bypasses it."""
    from agent_foundry.ai_models.inference import InferenceProvider, InferenceRequest

    class _NeverCallProvider(InferenceProvider):
        async def __call__(self, request: InferenceRequest) -> BaseModel:
            raise AssertionError("Provider should not be called when executor is set")

        async def close(self) -> None:
            pass

    return ModelEntry(
        model_id="fake",
        provider=_NeverCallProvider(),
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )


class TestAICallEvalExecutor:
    @pytest.mark.asyncio
    async def test_b6_custom_sync_executor_runs_not_invoke_ai_call(self) -> None:
        """B6: eval task calls the custom executor, not the underlying provider."""
        calls: list[dict] = []

        def spy_executor(*, primitive: Any, model_input: Any) -> _Output:
            calls.append({"primitive": primitive, "model_input": model_input})
            return _Output(result="from-spy")

        call = AICall[_Input, _Output](
            model_input=ModelInput[_Input](instructions="sys", prompt="usr"),
            parameters=InferenceParameters(max_tokens=16),
            model=_never_called_entry(),
            executor=spy_executor,
        )
        task = build_invoke_ai_call_task(call)
        result = await task(_Input(text="hello"))

        assert len(calls) == 1
        assert calls[0]["primitive"] is call
        assert calls[0]["model_input"].text == "hello"
        assert isinstance(result, _Output)
        assert result.result == "from-spy"

    @pytest.mark.asyncio
    async def test_b6_custom_async_executor_runs_not_invoke_ai_call(self) -> None:
        """B6: async custom executor is awaited by the eval task."""
        calls: list[dict] = []

        async def async_spy(*, primitive: Any, model_input: Any) -> _Output:
            calls.append({"primitive": primitive, "model_input": model_input})
            return _Output(result="from-async-spy")

        call = AICall[_Input, _Output](
            model_input=ModelInput[_Input](instructions="sys", prompt="usr"),
            parameters=InferenceParameters(max_tokens=16),
            model=_never_called_entry(),
            executor=async_spy,
        )
        task = build_invoke_ai_call_task(call)
        result = await task(_Input(text="async-hello"))

        assert len(calls) == 1
        assert calls[0]["model_input"].text == "async-hello"
        assert result.result == "from-async-spy"

    @pytest.mark.asyncio
    async def test_b6_no_executor_uses_invoke_ai_call(self) -> None:
        """B6/B1: executor=None → eval task falls back to invoke_ai_call (provider is called)."""
        from agent_foundry.ai_models.inference import InferenceProvider, InferenceRequest

        provider_calls: list[InferenceRequest] = []

        class _CapProvider(InferenceProvider):
            async def __call__(self, request: InferenceRequest) -> BaseModel:
                provider_calls.append(request)
                return _Output(result="from-provider")

            async def close(self) -> None:
                pass

        entry = ModelEntry(
            model_id="fake",
            provider=_CapProvider(),
            capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
        )
        call = AICall[_Input, _Output](
            model_input=ModelInput[_Input](instructions="sys", prompt="usr"),
            parameters=InferenceParameters(max_tokens=16),
            model=entry,
        )
        task = build_invoke_ai_call_task(call)
        result = await task(_Input(text="default"))

        assert len(provider_calls) == 1
        assert result.result == "from-provider"
