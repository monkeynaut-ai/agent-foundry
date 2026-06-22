"""Tests for ``agent_foundry.evals.registry.AICallRegistry``."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agent_foundry.ai_models.inference import InferenceParameters
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.constructs.ai_call import AICall, ModelInput
from agent_foundry.evals.registry import AICallRegistry, DuplicateAICallError, UnknownAICallError


class _Input(BaseModel):
    text: str


class _Output(BaseModel):
    result: str


def _stub_call() -> AICall[_Input, _Output]:
    entry = ModelEntry(
        model_id="fake",
        provider=object(),  # type: ignore[arg-type]  # not invoked in these tests
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )
    return AICall[_Input, _Output](
        model_input=ModelInput[_Input](instructions="i", prompt="p"),
        parameters=InferenceParameters(max_tokens=128),
        model=entry,
    )


def test_register_and_get_roundtrip() -> None:
    reg = AICallRegistry()
    call = _stub_call()
    reg.register("design_review", call)

    assert reg.get("design_review") is call


def test_get_unknown_raises() -> None:
    reg = AICallRegistry()
    with pytest.raises(UnknownAICallError, match="design_review"):
        reg.get("design_review")


def test_duplicate_register_raises() -> None:
    reg = AICallRegistry()
    reg.register("design_review", _stub_call())
    with pytest.raises(DuplicateAICallError, match="design_review"):
        reg.register("design_review", _stub_call())


def test_names_lists_registered() -> None:
    reg = AICallRegistry()
    reg.register("a", _stub_call())
    reg.register("b", _stub_call())
    assert sorted(reg.names()) == ["a", "b"]


def test_iter_yields_name_call_pairs() -> None:
    reg = AICallRegistry()
    a = _stub_call()
    b = _stub_call()
    reg.register("a", a)
    reg.register("b", b)

    items = dict(iter(reg))
    assert items == {"a": a, "b": b}


def test_contains_membership() -> None:
    reg = AICallRegistry()
    reg.register("a", _stub_call())
    assert "a" in reg
    assert "b" not in reg


def test_len_counts_registrations() -> None:
    reg = AICallRegistry()
    assert len(reg) == 0
    reg.register("a", _stub_call())
    assert len(reg) == 1
    reg.register("b", _stub_call())
    assert len(reg) == 2
