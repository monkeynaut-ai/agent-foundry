"""Tests for ``agent_foundry.ai_models.execute.invoke.invoke_ai_request``.

These tests exercise the direct-invocation path: no compiler, no
``RunContext``, no LangGraph. The helper is the single source of truth
for resolving ``AIRequest`` fields and calling the provider; both the
compiler node and out-of-band callers (e.g., the eval harness) consume
it.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agent_foundry.ai_models.execute.invoke import invoke_ai_request
from agent_foundry.ai_models.inference import (
    InferenceParameters,
    InferenceProvider,
    InferenceRequest,
)
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.primitives.ai_request import AIRequest, ModelInput


class _Input(BaseModel):
    text: str
    flag: bool = False


class _Output(BaseModel):
    result: str


class _CapturingProvider(InferenceProvider):
    def __init__(self, captured: list[InferenceRequest]) -> None:
        self._captured = captured

    async def __call__(self, request: InferenceRequest) -> BaseModel:
        self._captured.append(request)
        return _Output(result="ok")

    async def close(self) -> None:
        pass


def _capturing_entry(captured: list[InferenceRequest]) -> ModelEntry:
    return ModelEntry(
        model_id="fake",
        provider=_CapturingProvider(captured),
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )


@pytest.mark.asyncio
async def test_static_instructions_and_prompt_passed_to_provider() -> None:
    captured: list[InferenceRequest] = []
    req = AIRequest[_Input, _Output](
        model_input=ModelInput[_Input](
            instructions="system prompt",
            prompt="user message",
        ),
        parameters=InferenceParameters(max_tokens=256),
        model=_capturing_entry(captured),
    )

    output = await invoke_ai_request(req, _Input(text="hello"))

    assert len(captured) == 1
    assert captured[0].instructions == "system prompt"
    assert captured[0].prompt == "user message"
    assert isinstance(output, _Output)
    assert output.result == "ok"


@pytest.mark.asyncio
async def test_callable_instructions_and_prompt_resolved_from_state() -> None:
    captured: list[InferenceRequest] = []
    req = AIRequest[_Input, _Output](
        model_input=ModelInput[_Input](
            instructions=lambda s: f"system:{s.text}",
            prompt=lambda s: f"user:{s.text}",
        ),
        parameters=InferenceParameters(max_tokens=256),
        model=_capturing_entry(captured),
    )

    await invoke_ai_request(req, _Input(text="world"))

    assert captured[0].instructions == "system:world"
    assert captured[0].prompt == "user:world"


@pytest.mark.asyncio
async def test_static_parameters_passed_to_provider() -> None:
    captured: list[InferenceRequest] = []
    params = InferenceParameters(max_tokens=512, temperature=0.3)
    req = AIRequest[_Input, _Output](
        model_input=ModelInput[_Input](instructions="i", prompt="p"),
        parameters=params,
        model=_capturing_entry(captured),
    )

    await invoke_ai_request(req, _Input(text="x"))

    assert captured[0].parameters.max_tokens == 512
    assert captured[0].parameters.temperature == 0.3


@pytest.mark.asyncio
async def test_callable_parameters_resolved_from_state() -> None:
    captured: list[InferenceRequest] = []

    def _params(state: _Input) -> InferenceParameters:
        return InferenceParameters(max_tokens=1024 if state.flag else 128)

    req = AIRequest[_Input, _Output](
        model_input=ModelInput[_Input](instructions="i", prompt="p"),
        parameters=_params,
        model=_capturing_entry(captured),
    )

    await invoke_ai_request(req, _Input(text="x", flag=True))
    assert captured[0].parameters.max_tokens == 1024

    await invoke_ai_request(req, _Input(text="x", flag=False))
    assert captured[1].parameters.max_tokens == 128


@pytest.mark.asyncio
async def test_callable_model_selected_from_state() -> None:
    captured_a: list[InferenceRequest] = []
    captured_b: list[InferenceRequest] = []
    entry_a = _capturing_entry(captured_a)
    entry_b = _capturing_entry(captured_b)

    req = AIRequest[_Input, _Output](
        model_input=ModelInput[_Input](instructions="i", prompt="p"),
        parameters=InferenceParameters(max_tokens=256),
        model=lambda state: entry_a if state.flag else entry_b,
    )

    await invoke_ai_request(req, _Input(text="x", flag=True))
    assert len(captured_a) == 1
    assert len(captured_b) == 0

    await invoke_ai_request(req, _Input(text="x", flag=False))
    assert len(captured_a) == 1
    assert len(captured_b) == 1


@pytest.mark.asyncio
async def test_model_id_from_model_entry_passed_to_provider() -> None:
    """The ModelEntry.model_id flows into request.model_id so the provider
    knows which backend model to call. Model identity is call-time data,
    not part of provider identity."""
    captured: list[InferenceRequest] = []
    entry = ModelEntry(
        model_id="claude-haiku-4-5-20251001",
        provider=_CapturingProvider(captured),
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )
    req = AIRequest[_Input, _Output](
        model_input=ModelInput[_Input](instructions="i", prompt="p"),
        parameters=InferenceParameters(max_tokens=256),
        model=entry,
    )

    await invoke_ai_request(req, _Input(text="x"))

    assert captured[0].model_id == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_output_type_passed_to_provider() -> None:
    captured: list[InferenceRequest] = []
    req = AIRequest[_Input, _Output](
        model_input=ModelInput[_Input](instructions="i", prompt="p"),
        parameters=InferenceParameters(max_tokens=256),
        model=_capturing_entry(captured),
    )

    await invoke_ai_request(req, _Input(text="x"))

    assert captured[0].output_type is _Output


@pytest.mark.asyncio
async def test_provider_returning_wrong_type_raises() -> None:
    class WrongOutput(BaseModel):
        other: str

    class _BadProvider(InferenceProvider):
        async def __call__(self, request: InferenceRequest) -> BaseModel:
            return WrongOutput(other="wrong")

        async def close(self) -> None:
            pass

    entry = ModelEntry(
        model_id="fake",
        provider=_BadProvider(),
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )
    req = AIRequest[_Input, _Output](
        model_input=ModelInput[_Input](instructions="i", prompt="p"),
        parameters=InferenceParameters(max_tokens=256),
        model=entry,
    )

    with pytest.raises(TypeError):
        await invoke_ai_request(req, _Input(text="x"))
