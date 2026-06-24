"""Capability-aware inference: invoke_ai_call honors ModelCapabilities.

- ``thinking`` on a model that can't do it is a loud error on the primary,
  but dropped on a fallback so failover still works.
- ``max_tokens`` defaults to the model's ``max_output_tokens`` and is clamped
  to it — never silently exceeding the model's cap.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agent_foundry.ai_models.execute.invoke import invoke_ai_call
from agent_foundry.ai_models.inference import (
    InferenceParameters,
    InferenceProvider,
    InferenceRequest,
    InferenceResult,
)
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.ai_models.resilience import RetryPolicy
from agent_foundry.constructs.ai_call import AICall, ModelInput


class _Input(BaseModel):
    text: str


class _Output(BaseModel):
    result: str


class _Persistent(Exception):
    pass


class _CapturingProvider(InferenceProvider):
    def __init__(self, captured: list[InferenceRequest], *, fail: Exception | None = None) -> None:
        self._captured = captured
        self._fail = fail

    async def __call__(self, request: InferenceRequest) -> InferenceResult:
        self._captured.append(request)
        if self._fail is not None:
            raise self._fail
        return InferenceResult(output=_Output(result="ok"), usage=None)

    async def close(self) -> None:
        pass


def _entry(provider, *, model_id="m", max_output=100, thinking=False, fallback=None):
    return ModelEntry(
        model_id=model_id,
        provider=provider,
        capabilities=ModelCapabilities(
            context_window=1000, max_output_tokens=max_output, supports_thinking=thinking
        ),
        fallback=fallback,
    )


def _call(model, *, params, fallbacks=None):
    return AICall[_Input, _Output](
        model_input=ModelInput(instructions="i", prompt="p"),
        model=model,
        parameters=params,
        retry=RetryPolicy(max_attempts=1, backoff_base_seconds=0.0),
        fallbacks=fallbacks,
    )


@pytest.mark.asyncio
async def test_thinking_on_unsupported_primary_raises() -> None:
    entry = _entry(_CapturingProvider([]), thinking=False)
    construct = _call(entry, params=InferenceParameters(thinking=True), fallbacks=[])
    with pytest.raises(ValueError, match="supports_thinking is False"):
        await invoke_ai_call(construct=construct, model_input=_Input(text="x"))


@pytest.mark.asyncio
async def test_effort_on_unsupported_primary_raises() -> None:
    entry = _entry(_CapturingProvider([]), thinking=False)
    construct = _call(entry, params=InferenceParameters(effort="high"), fallbacks=[])
    with pytest.raises(ValueError, match="supports_thinking is False"):
        await invoke_ai_call(construct=construct, model_input=_Input(text="x"))


@pytest.mark.asyncio
async def test_effort_passed_through_when_supported() -> None:
    captured: list[InferenceRequest] = []
    entry = _entry(_CapturingProvider(captured), thinking=True)
    construct = _call(entry, params=InferenceParameters(effort="low"), fallbacks=[])
    await invoke_ai_call(construct=construct, model_input=_Input(text="x"))
    assert captured[0].parameters.effort == "low"


@pytest.mark.asyncio
async def test_thinking_bool_resolves_to_default_effort() -> None:
    captured: list[InferenceRequest] = []
    entry = _entry(_CapturingProvider(captured), thinking=True)
    construct = _call(entry, params=InferenceParameters(thinking=True), fallbacks=[])
    await invoke_ai_call(construct=construct, model_input=_Input(text="x"))
    # The coarse thinking bool resolves to a default effort; thinking normalized away.
    assert captured[0].parameters.effort == "medium"
    assert captured[0].parameters.thinking is None


@pytest.mark.asyncio
async def test_effort_none_is_not_reasoning() -> None:
    # Explicit "none" means no reasoning — allowed even on a non-thinking model.
    captured: list[InferenceRequest] = []
    entry = _entry(_CapturingProvider(captured), thinking=False)
    construct = _call(entry, params=InferenceParameters(effort="none"), fallbacks=[])
    await invoke_ai_call(construct=construct, model_input=_Input(text="x"))
    assert captured[0].parameters.effort is None


@pytest.mark.asyncio
async def test_thinking_dropped_on_fallback() -> None:
    captured: list[InferenceRequest] = []
    primary = _entry(_CapturingProvider([], fail=_Persistent()), model_id="primary", thinking=True)
    fallback = _entry(_CapturingProvider(captured), model_id="fb", thinking=False)
    construct = _call(primary, params=InferenceParameters(thinking=True), fallbacks=[fallback])
    result = await invoke_ai_call(construct=construct, model_input=_Input(text="x"))
    assert result.output.result == "ok"
    # The fallback can't think, so thinking was dropped rather than raising.
    assert captured[0].parameters.thinking is None


@pytest.mark.asyncio
async def test_max_tokens_defaults_to_model_cap_when_unset() -> None:
    captured: list[InferenceRequest] = []
    entry = _entry(_CapturingProvider(captured), max_output=100)
    construct = _call(entry, params=InferenceParameters(), fallbacks=[])
    await invoke_ai_call(construct=construct, model_input=_Input(text="x"))
    assert captured[0].parameters.max_tokens == 100


@pytest.mark.asyncio
async def test_max_tokens_clamped_to_model_cap_when_over() -> None:
    captured: list[InferenceRequest] = []
    entry = _entry(_CapturingProvider(captured), max_output=100)
    construct = _call(entry, params=InferenceParameters(max_tokens=500), fallbacks=[])
    await invoke_ai_call(construct=construct, model_input=_Input(text="x"))
    assert captured[0].parameters.max_tokens == 100


@pytest.mark.asyncio
async def test_max_tokens_preserved_when_under_cap() -> None:
    captured: list[InferenceRequest] = []
    entry = _entry(_CapturingProvider(captured), max_output=100)
    construct = _call(entry, params=InferenceParameters(max_tokens=50), fallbacks=[])
    await invoke_ai_call(construct=construct, model_input=_Input(text="x"))
    assert captured[0].parameters.max_tokens == 50
