"""FunctionAction and AICall carry an optional diagnostic ``name``.

Mirrors ``AgentAction.name`` but optional — when None the compiler falls
back to the positional node_id for lifecycle labelling.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from agent_foundry.ai_models.inference import InferenceParameters
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.primitives.ai_call import AICall, ModelInput
from agent_foundry.primitives.models import FunctionAction


class _Input(BaseModel):
    text: str


class _Output(BaseModel):
    result: str


def _model_entry() -> ModelEntry:
    return ModelEntry(
        model_id="fake",
        provider=object(),  # never invoked in these construction-only tests
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )


def _function_action(**kw) -> FunctionAction:
    return FunctionAction[_Input, _Output](function=lambda s: _Output(result="y"), **kw)


def _ai_call(**kw) -> AICall:
    return AICall[_Input, _Output](
        model_input=ModelInput[_Input](instructions="s", prompt="p"),
        parameters=InferenceParameters(max_tokens=16),
        model=_model_entry(),
        **kw,
    )


def test_function_action_name_defaults_none() -> None:
    assert _function_action().name is None


def test_function_action_accepts_name() -> None:
    assert _function_action(name="aggregate_design_verdict").name == "aggregate_design_verdict"


def test_function_action_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        _function_action(name="")


def test_ai_call_name_defaults_none() -> None:
    assert _ai_call().name is None


def test_ai_call_accepts_name() -> None:
    assert _ai_call(name="design_correctness_review").name == "design_correctness_review"


def test_ai_call_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        _ai_call(name="")
