"""Tests for ``agent_foundry.evals.api.schemas``."""

from __future__ import annotations

from pydantic import BaseModel

from agent_foundry.ai_models.inference import InferenceParameters
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.evals.api.schemas import TargetSpec, target_spec_from_ai_call
from agent_foundry.evals.models import EvalTargetKind
from agent_foundry.primitives.ai_call import AICall, ModelInput


class _Input(BaseModel):
    text: str
    flag: bool = False


class _Output(BaseModel):
    result: str


def _make_ai_call() -> AICall[_Input, _Output]:
    entry = ModelEntry(
        model_id="claude-haiku-4-5-20251001",
        provider=object(),  # type: ignore[arg-type]  # not invoked in schema-only tests
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )
    return AICall[_Input, _Output](
        model_input=ModelInput[_Input](instructions="i", prompt="p"),
        parameters=InferenceParameters(max_tokens=128),
        model=entry,
    )


def test_target_spec_from_ai_call_populates_name_and_kind() -> None:
    spec = target_spec_from_ai_call("design_review", _make_ai_call())

    assert isinstance(spec, TargetSpec)
    assert spec.name == "design_review"
    assert spec.kind is EvalTargetKind.AI_CALL


def test_target_spec_from_ai_call_includes_input_schema() -> None:
    spec = target_spec_from_ai_call("design_review", _make_ai_call())

    assert spec.input_schema["title"] == "_Input"
    assert "text" in spec.input_schema["properties"]
    assert "flag" in spec.input_schema["properties"]


def test_target_spec_from_ai_call_includes_output_schema() -> None:
    spec = target_spec_from_ai_call("design_review", _make_ai_call())

    assert spec.output_schema["title"] == "_Output"
    assert "result" in spec.output_schema["properties"]


def test_target_spec_serializes_to_json() -> None:
    spec = target_spec_from_ai_call("design_review", _make_ai_call())
    data = spec.model_dump(mode="json")

    assert data["name"] == "design_review"
    assert data["kind"] == "ai_call"
    assert isinstance(data["input_schema"], dict)
    assert isinstance(data["output_schema"], dict)
