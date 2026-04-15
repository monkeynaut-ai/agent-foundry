"""F0 happy-path executor smoke tests.

Migrated to the F.3 driver contract: the adapter now returns
``(envelope_dict, session_id)`` and is installed via the
``set_driver_factory`` seam. Clarification / permission outcomes are
handled by the F.3 inner loop (see ``test_container_executor.py``);
the legacy "raises NotImplementedError" check has been retired.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agent_foundry.orchestration import container_executor
from agent_foundry.orchestration.container_executor import run_agent_in_container
from agent_foundry.orchestration.registry import AgentContainerRegistry
from agent_foundry.orchestration.run_context import (
    AgentRunContext,
    NoOpLifecycleWriter,
)
from agent_foundry.primitives.models import (
    AgentAction,
    ContainerReusePolicy,
)

from .fakes import FakeClaudeCodeDriver, FakeContainerManager


class InputModel(BaseModel):
    task: str


class OutputModel(BaseModel):
    answer: str


def _make_primitive() -> AgentAction[InputModel, OutputModel]:
    return AgentAction[InputModel, OutputModel](
        name="test-agent",
        prompt_builder=lambda s: f"do: {s.task}",
        instructions_provider=lambda: "Be precise.",
        executor=run_agent_in_container,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    )


def _install_driver(monkeypatch: pytest.MonkeyPatch, driver: FakeClaudeCodeDriver) -> None:
    """Swap the module-level ``_run_claude_turn`` for a scripted fake."""
    monkeypatch.setattr(container_executor, "_run_claude_turn", driver)


@pytest.mark.asyncio
async def test_run_agent_in_container_happy_path(monkeypatch) -> None:
    driver = FakeClaudeCodeDriver(
        turn_script=[
            {"outcome": {"kind": "success", "payload": {"answer": "42"}}},
        ],
        session_ids=["sess-f0"],
    )
    _install_driver(monkeypatch, driver)

    fake_mgr = FakeContainerManager()
    registry = AgentContainerRegistry(
        manager=fake_mgr,
        base_image_tag="agent-foundry-base:test",
        workspace_volume="vol-f0",
    )
    ctx = AgentRunContext(
        run_id="run-f0",
        container_registry=registry,
        lifecycle_writer=NoOpLifecycleWriter(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    primitive = _make_primitive()
    result = await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)
    assert isinstance(result, OutputModel)
    assert result.answer == "42"
    # Container was created and is running; the F.3 lifecycle keeps the
    # container alive for subsequent invocations (destroyed by
    # registry.shutdown_all at end of run).
    assert fake_mgr.handles[0].status == "running"
    # Driver contract: new F.3 shape records per-call args.
    assert len(driver.calls) == 1
    assert driver.calls[0]["resume"] is None


@pytest.mark.asyncio
async def test_run_agent_in_container_failure_outcome_raises(
    monkeypatch,
) -> None:
    """FailureOutcome surfaces as AgentFailedError (F.3 contract)."""
    from agent_foundry.orchestration.errors import AgentFailedError

    driver = FakeClaudeCodeDriver(
        turn_script=[
            {
                "outcome": {
                    "kind": "failed",
                    "reason": "cannot proceed",
                    "attempted_approaches": [],
                }
            }
        ],
        session_ids=["sess-f0-fail"],
    )
    _install_driver(monkeypatch, driver)

    fake_mgr = FakeContainerManager()
    registry = AgentContainerRegistry(
        manager=fake_mgr,
        base_image_tag="x",
        workspace_volume="v",
    )
    ctx = AgentRunContext(
        run_id="r",
        container_registry=registry,
        lifecycle_writer=NoOpLifecycleWriter(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "t"},
    )
    primitive = _make_primitive()
    with pytest.raises(AgentFailedError) as excinfo:
        await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)
    assert "cannot proceed" in excinfo.value.reason
