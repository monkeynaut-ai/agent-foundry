"""Tests for the agent runner stub (Plan 1 scope).

The real implementation lands in Plan 2. This test file verifies that
``run_agent_in_container`` is importable and raises NotImplementedError
when called — so real invocations before Plan 2 fail loudly rather than
silently.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agent_foundry.acp.agent_runner import run_agent_in_container
from agent_foundry.primitives.models import (
    AgentAction,
    ContainerReusePolicy,
    StructuredOutputChannel,
)


class _StubInput(BaseModel):
    value: str


class _StubOutput(BaseModel):
    result: str


class TestRunAgentInContainerStub:
    @pytest.mark.parametrize("policy", list(ContainerReusePolicy))
    def test_raises_not_implemented_error_for_every_reuse_policy(self, policy):
        # The stub ignores reuse_policy; all values raise NotImplementedError.
        # Plan 2 will implement policy-specific behavior — this test pins
        # the stub's policy-agnostic contract until then.
        action = AgentAction[_StubInput, _StubOutput](
            prompt_builder=lambda s: "prompt",
            instructions_provider=lambda: "instructions",
            response_channel=StructuredOutputChannel(),
            executor=run_agent_in_container,
            reuse_policy=policy,
        )
        with pytest.raises(NotImplementedError, match="Plan 2"):
            run_agent_in_container(primitive=action, prompt="hi")
