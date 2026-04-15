from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_foundry.orchestration.run_context import (
    AgentRunContext,
    NoOpLifecycleWriter,
)


def test_agent_run_context_has_required_f0_fields() -> None:
    ctx = AgentRunContext(
        run_id="run-1",
        container_registry=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    assert ctx.run_id == "run-1"
    assert ctx.env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok"


def test_no_op_lifecycle_writer_accepts_append_and_discards() -> None:
    writer = NoOpLifecycleWriter()
    # Must not raise; must not persist anywhere visible.
    writer.append({"type": "anything", "payload": {"x": 1}})
    writer.append({"type": "other"})
    # No public read surface — the whole point is that it's a sink.


def test_agent_run_context_env_is_required() -> None:
    with pytest.raises(ValidationError):
        AgentRunContext(  # type: ignore[call-arg]
            run_id="r",
            container_registry=object(),
            lifecycle_writer=NoOpLifecycleWriter(),
        )
