"""Tests for the AgentAction primitive model."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from agent_foundry.primitives.models import (
    AgentAction,
    ContainerReusePolicy,
    get_type_args,
)


class StubInput(BaseModel):
    value: str


class StubOutput(BaseModel):
    result: str


# ======================================================================
# ContainerReusePolicy
# ======================================================================


class TestContainerReusePolicy:
    """ContainerReusePolicy enumerates supported reuse modes."""

    def test_has_new_each_time(self):
        assert ContainerReusePolicy.NEW_EACH_TIME.value == "new_each_time"

    def test_has_reuse_resume(self):
        assert ContainerReusePolicy.REUSE_RESUME.value == "reuse_resume"

    def test_has_reuse_new_session(self):
        assert ContainerReusePolicy.REUSE_NEW_SESSION.value == "reuse_new_session"

    def test_is_str_enum(self):
        assert ContainerReusePolicy.NEW_EACH_TIME == "new_each_time"


# ======================================================================
# AgentAction — required fields
# ======================================================================


def _stub_prompt_builder(state: StubInput) -> str:
    return f"prompt: {state.value}"


def _stub_instructions_provider() -> str:
    return "# Agent instructions\n\nDo the thing."


class TestAgentActionRequiredFields:
    """AgentAction requires prompt_builder and instructions_provider."""

    def test_given_all_required_fields_when_created_then_succeeds(self):
        action = AgentAction[StubInput, StubOutput](
            prompt_builder=_stub_prompt_builder,
            instructions_provider=_stub_instructions_provider,
        )
        assert callable(action.prompt_builder)
        assert callable(action.instructions_provider)

    def test_unparameterized_raises(self):
        with pytest.raises(ValidationError, match="must be parameterized"):
            AgentAction(
                prompt_builder=_stub_prompt_builder,
                instructions_provider=_stub_instructions_provider,
            )

    def test_missing_prompt_builder_raises(self):
        with pytest.raises(ValidationError):
            AgentAction[StubInput, StubOutput](
                instructions_provider=_stub_instructions_provider,
            )

    def test_missing_instructions_provider_raises(self):
        with pytest.raises(ValidationError):
            AgentAction[StubInput, StubOutput](
                prompt_builder=_stub_prompt_builder,
            )

    def test_get_type_args_returns_parameterized_types(self):
        action = AgentAction[StubInput, StubOutput](
            prompt_builder=_stub_prompt_builder,
            instructions_provider=_stub_instructions_provider,
        )
        input_type, output_type = get_type_args(action)
        assert input_type is StubInput
        assert output_type is StubOutput

    def test_prompt_builder_is_callable(self):
        action = AgentAction[StubInput, StubOutput](
            prompt_builder=_stub_prompt_builder,
            instructions_provider=_stub_instructions_provider,
        )
        result = action.prompt_builder(StubInput(value="hello"))
        assert result == "prompt: hello"

    def test_instructions_provider_is_callable(self):
        action = AgentAction[StubInput, StubOutput](
            prompt_builder=_stub_prompt_builder,
            instructions_provider=_stub_instructions_provider,
        )
        text = action.instructions_provider()
        assert text.startswith("# Agent instructions")
