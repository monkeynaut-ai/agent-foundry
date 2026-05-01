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

    def test_has_reuse_resume(self):
        assert ContainerReusePolicy.REUSE_RESUME.value == "reuse_resume"

    def test_has_reuse_new_session(self):
        assert ContainerReusePolicy.REUSE_NEW_SESSION.value == "reuse_new_session"

    def test_is_str_enum(self):
        assert ContainerReusePolicy.REUSE_RESUME == "reuse_resume"

    def test_container_reuse_policy_has_exactly_two_members(self):
        assert set(ContainerReusePolicy) == {
            ContainerReusePolicy.REUSE_RESUME,
            ContainerReusePolicy.REUSE_NEW_SESSION,
        }


# ======================================================================
# AgentAction — required fields
# ======================================================================


def _stub_prompt_builder(state: StubInput) -> str:
    return f"prompt: {state.value}"


def _stub_instructions_provider(_state: object) -> str:
    return "# Agent instructions\n\nDo the thing."


def _stub_executor_for_required(*, primitive, prompt) -> StubOutput:
    return StubOutput(result="stub")


class TestAgentActionRequiredFields:
    """AgentAction requires prompt_builder and instructions_provider."""

    def test_given_all_required_fields_when_created_then_succeeds(self):
        action = AgentAction[StubInput, StubOutput](
            name="test-agent",
            prompt_builder=_stub_prompt_builder,
            instructions_provider=_stub_instructions_provider,
            executor=_stub_executor_for_required,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        assert callable(action.prompt_builder)
        assert callable(action.instructions_provider)

    def test_unparameterized_raises(self):
        with pytest.raises(ValidationError, match="must be parameterized"):
            AgentAction(
                name="test-agent",
                prompt_builder=_stub_prompt_builder,
                instructions_provider=_stub_instructions_provider,
                executor=_stub_executor_for_required,
                reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            )

    def test_missing_prompt_builder_raises(self):
        with pytest.raises(ValidationError):
            AgentAction[StubInput, StubOutput](
                instructions_provider=_stub_instructions_provider,
                executor=_stub_executor_for_required,
                reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            )

    def test_missing_instructions_provider_raises(self):
        with pytest.raises(ValidationError):
            AgentAction[StubInput, StubOutput](
                prompt_builder=_stub_prompt_builder,
                executor=_stub_executor_for_required,
                reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            )

    def test_get_type_args_returns_parameterized_types(self):
        action = AgentAction[StubInput, StubOutput](
            name="test-agent",
            prompt_builder=_stub_prompt_builder,
            instructions_provider=_stub_instructions_provider,
            executor=_stub_executor_for_required,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        input_type, output_type = get_type_args(action)
        assert input_type is StubInput
        assert output_type is StubOutput

    def test_prompt_builder_is_callable(self):
        action = AgentAction[StubInput, StubOutput](
            name="test-agent",
            prompt_builder=_stub_prompt_builder,
            instructions_provider=_stub_instructions_provider,
            executor=_stub_executor_for_required,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        result = action.prompt_builder(StubInput(value="hello"))
        assert result == "prompt: hello"

    def test_instructions_provider_is_callable(self):
        action = AgentAction[StubInput, StubOutput](
            name="test-agent",
            prompt_builder=_stub_prompt_builder,
            instructions_provider=_stub_instructions_provider,
            executor=_stub_executor_for_required,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        text = action.instructions_provider(StubInput(value="probe"))
        assert text.startswith("# Agent instructions")


# ======================================================================
# AgentAction — no response channel (structured output only)
# ======================================================================


class TestAgentActionNoResponseChannel:
    """AgentAction carries no response_channel field.

    Every agent uses structured output; the channel abstraction is gone.
    """

    def test_response_channel_not_in_model_fields(self):
        assert "response_channel" not in AgentAction.model_fields

    def test_no_response_channel_class_attr(self):
        assert not hasattr(AgentAction, "response_channel")

    def test_no_response_channel_instance_attr(self):
        action = AgentAction[StubInput, StubOutput](
            name="test-agent",
            prompt_builder=_stub_prompt_builder,
            instructions_provider=_stub_instructions_provider,
            executor=_stub_executor_for_required,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        assert not hasattr(action, "response_channel")


# ======================================================================
# AgentAction — executor
# ======================================================================


def _stub_executor(*, primitive, prompt) -> StubOutput:
    return StubOutput(result="stub")


class TestAgentActionExecutor:
    """executor is required; product supplies the callable that runs the agent."""

    def test_missing_executor_raises(self):
        with pytest.raises(ValidationError):
            AgentAction[StubInput, StubOutput](
                prompt_builder=_stub_prompt_builder,
                instructions_provider=_stub_instructions_provider,
                reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            )

    def test_executor_accepted(self):
        action = AgentAction[StubInput, StubOutput](
            name="test-agent",
            prompt_builder=_stub_prompt_builder,
            instructions_provider=_stub_instructions_provider,
            executor=_stub_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        assert action.executor is _stub_executor

    def test_executor_is_callable(self):
        action = AgentAction[StubInput, StubOutput](
            name="test-agent",
            prompt_builder=_stub_prompt_builder,
            instructions_provider=_stub_instructions_provider,
            executor=_stub_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        )
        result = action.executor(primitive=action, prompt="hi")
        assert result == StubOutput(result="stub")


# ======================================================================
# AgentAction — configuration fields with platform defaults
# ======================================================================


def _new_structured_action() -> AgentAction:
    return AgentAction[StubInput, StubOutput](
        name="test-agent",
        prompt_builder=_stub_prompt_builder,
        instructions_provider=_stub_instructions_provider,
        executor=_stub_executor,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    )


class TestAgentActionConfigFields:
    """AgentAction has configuration fields with platform defaults."""

    def test_timeout_seconds_defaults_to_3600(self):
        action = _new_structured_action()
        assert action.timeout_seconds == 3600

    def test_timeout_seconds_must_be_positive(self):
        with pytest.raises(ValidationError):
            AgentAction[StubInput, StubOutput](
                name="test-agent",
                prompt_builder=_stub_prompt_builder,
                instructions_provider=_stub_instructions_provider,
                executor=_stub_executor,
                timeout_seconds=0,
                reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            )

    def test_skip_permissions_defaults_to_false(self):
        action = _new_structured_action()
        assert action.skip_permissions is False

    def test_reuse_policy_is_required(self):
        with pytest.raises(ValidationError, match="reuse_policy"):
            AgentAction[StubInput, StubOutput](
                prompt_builder=_stub_prompt_builder,
                instructions_provider=_stub_instructions_provider,
                executor=_stub_executor,
            )

    def test_reuse_policy_accepts_all_values(self):
        for policy in ContainerReusePolicy:
            action = AgentAction[StubInput, StubOutput](
                name="test-agent",
                prompt_builder=_stub_prompt_builder,
                instructions_provider=_stub_instructions_provider,
                executor=_stub_executor,
                reuse_policy=policy,
            )
            assert action.reuse_policy == policy


# ======================================================================
# AgentAction — gids field
# ======================================================================


class TestAgentActionGids:
    """AgentAction.gids declares which GIDs the agent process should hold."""

    def test_given_no_gids_when_created_then_defaults_to_empty_list(self):
        assert _new_structured_action().gids == []

    def test_given_gids_list_when_created_then_stored(self):
        action = AgentAction[StubInput, StubOutput](
            name="writer",
            prompt_builder=_stub_prompt_builder,
            instructions_provider=_stub_instructions_provider,
            executor=_stub_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            gids=[1001, 1002],
        )
        assert action.gids == [1001, 1002]

    def test_given_empty_gids_when_created_then_valid_read_only_agent(self):
        action = AgentAction[StubInput, StubOutput](
            name="reader",
            prompt_builder=_stub_prompt_builder,
            instructions_provider=_stub_instructions_provider,
            executor=_stub_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            gids=[],
        )
        assert action.gids == []

    def test_given_single_gid_when_created_then_accepted(self):
        action = AgentAction[StubInput, StubOutput](
            name="documents-writer",
            prompt_builder=_stub_prompt_builder,
            instructions_provider=_stub_instructions_provider,
            executor=_stub_executor,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            gids=[1001],
        )
        assert action.gids == [1001]
