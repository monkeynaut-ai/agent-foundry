"""Tests for the AgentAction primitive model."""

from __future__ import annotations

from pydantic import BaseModel

from agent_foundry.primitives.models import (
    ContainerReusePolicy,
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
