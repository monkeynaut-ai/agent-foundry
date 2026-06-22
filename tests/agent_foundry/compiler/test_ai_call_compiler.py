"""Tests for the AICall compiler node."""

from __future__ import annotations

import asyncio

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
from agent_foundry.constructs.errors import ConstructCompilationError
from agent_foundry.constructs.process import Process


class Input(BaseModel):
    text: str
    flag: bool = False


class Output(BaseModel):
    result: str


@pytest.fixture(autouse=True)
def _default_run_context(tmp_path):
    from agent_foundry.orchestration.run_context import (
        NoOpLifecycleWriter,
        RunContext,
        current_run_context,
    )

    ctx = RunContext(
        run_id="ai-request-compiler-test",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    token = current_run_context.set(ctx)
    try:
        yield
    finally:
        current_run_context.reset(token)


class _CapturingProvider(InferenceProvider):
    def __init__(self, captured: list[InferenceRequest]) -> None:
        self._captured = captured

    async def __call__(self, request: InferenceRequest) -> InferenceResult:
        self._captured.append(request)
        return InferenceResult(output=Output(result="ok"))

    async def close(self) -> None:
        pass


def _fake_entry(captured: list[InferenceRequest]) -> ModelEntry:
    return ModelEntry(
        model_id="fake",
        provider=_CapturingProvider(captured),
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )


class TestAICallCompilerFieldResolution:
    def test_static_instructions_and_prompt_passed_to_provider(self):
        captured: list[InferenceRequest] = []
        action = AICall[Input, Output](
            model_input=ModelInput[Input](
                instructions="system prompt",
                prompt="user message",
            ),
            parameters=InferenceParameters(max_tokens=256),
            model=_fake_entry(captured),
        )
        graph = compile_process(Process(action))
        asyncio.run(graph.ainvoke({"text": "hello"}))

        assert len(captured) == 1
        assert captured[0].instructions == "system prompt"
        assert captured[0].prompt == "user message"

    def test_callable_instructions_and_prompt_resolved_from_state(self):
        captured: list[InferenceRequest] = []
        action = AICall[Input, Output](
            model_input=ModelInput[Input](
                instructions=lambda s: f"system:{s.text}",
                prompt=lambda s: f"user:{s.text}",
            ),
            parameters=InferenceParameters(max_tokens=256),
            model=_fake_entry(captured),
        )
        graph = compile_process(Process(action))
        asyncio.run(graph.ainvoke({"text": "world"}))

        assert captured[0].instructions == "system:world"
        assert captured[0].prompt == "user:world"

    def test_static_parameters_passed_to_provider(self):
        captured: list[InferenceRequest] = []
        params = InferenceParameters(max_tokens=512, temperature=0.3)
        action = AICall[Input, Output](
            model_input=ModelInput[Input](instructions="i", prompt="p"),
            parameters=params,
            model=_fake_entry(captured),
        )
        graph = compile_process(Process(action))
        asyncio.run(graph.ainvoke({"text": "x"}))

        assert captured[0].parameters.max_tokens == 512
        assert captured[0].parameters.temperature == 0.3

    def test_callable_parameters_resolved_from_state(self):
        captured: list[InferenceRequest] = []

        def _params(state: Input) -> InferenceParameters:
            return InferenceParameters(max_tokens=1024 if state.flag else 128)

        action = AICall[Input, Output](
            model_input=ModelInput[Input](instructions="i", prompt="p"),
            parameters=_params,
            model=_fake_entry(captured),
        )
        graph = compile_process(Process(action))
        asyncio.run(graph.ainvoke({"text": "x", "flag": True}))

        assert captured[0].parameters.max_tokens == 1024

    def test_output_type_passed_to_provider(self):
        captured: list[InferenceRequest] = []
        action = AICall[Input, Output](
            model_input=ModelInput[Input](instructions="i", prompt="p"),
            parameters=InferenceParameters(max_tokens=256),
            model=_fake_entry(captured),
        )
        graph = compile_process(Process(action))
        asyncio.run(graph.ainvoke({"text": "x"}))

        assert captured[0].output_type is Output

    def test_provider_output_merged_into_state(self):
        captured: list[InferenceRequest] = []
        action = AICall[Input, Output](
            model_input=ModelInput[Input](instructions="i", prompt="p"),
            parameters=InferenceParameters(max_tokens=256),
            model=_fake_entry(captured),
        )
        graph = compile_process(Process(action))
        result = asyncio.run(graph.ainvoke({"text": "x"}))

        assert result["result"] == "ok"


class TestAICallCompilerModelSelection:
    def test_callable_model_selected_from_state(self):
        captured_a: list[InferenceRequest] = []
        captured_b: list[InferenceRequest] = []
        entry_a = _fake_entry(captured_a)
        entry_b = _fake_entry(captured_b)

        action = AICall[Input, Output](
            model_input=ModelInput[Input](instructions="i", prompt="p"),
            parameters=InferenceParameters(max_tokens=256),
            model=lambda state: entry_a if state.flag else entry_b,
        )
        graph = compile_process(Process(action))

        asyncio.run(graph.ainvoke({"text": "x", "flag": True}))
        assert len(captured_a) == 1
        assert len(captured_b) == 0

        asyncio.run(graph.ainvoke({"text": "x", "flag": False}))
        assert len(captured_a) == 1
        assert len(captured_b) == 1


class TestAICallCompilerOutputValidation:
    def test_provider_returning_wrong_type_raises(self):
        class WrongOutput(BaseModel):
            other: str

        class _BadProvider(InferenceProvider):
            async def __call__(self, request: InferenceRequest) -> InferenceResult:
                return InferenceResult(output=WrongOutput(other="wrong"))

            async def close(self) -> None:
                pass

        entry = ModelEntry(
            model_id="fake",
            provider=_BadProvider(),
            capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
        )
        action = AICall[Input, Output](
            model_input=ModelInput[Input](instructions="i", prompt="p"),
            parameters=InferenceParameters(max_tokens=256),
            model=entry,
        )
        graph = compile_process(Process(action))

        with pytest.raises(ConstructCompilationError):
            asyncio.run(graph.ainvoke({"text": "x"}))
