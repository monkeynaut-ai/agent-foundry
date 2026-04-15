from __future__ import annotations

from typing import Any

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

from .fakes import FakeClaudeCodeAdapter, FakeContainerManager


class InputModel(BaseModel):
    task: str


class OutputModel(BaseModel):
    answer: str


def _make_primitive() -> AgentAction[InputModel, OutputModel]:
    return AgentAction[InputModel, OutputModel](
        prompt_builder=lambda s: f"do: {s.task}",
        instructions_provider=lambda: "Be precise.",
        executor=run_agent_in_container,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    )


@pytest.fixture
def patch_adapter(monkeypatch) -> list[FakeClaudeCodeAdapter]:
    holder: list[FakeClaudeCodeAdapter] = []

    def factory(*a: Any, **kw: Any) -> FakeClaudeCodeAdapter:
        adapter = FakeClaudeCodeAdapter(
            canned_structured_output={
                "outcome": {
                    "kind": "success",
                    "payload": {"answer": "42"},
                }
            },
        )
        holder.append(adapter)
        return adapter

    monkeypatch.setattr(container_executor, "build_adapter", factory)
    return holder


@pytest.mark.asyncio
async def test_run_agent_in_container_happy_path(patch_adapter) -> None:
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
    # Container was created and destroyed.
    assert fake_mgr.handles[0].status == "destroyed"


@pytest.mark.asyncio
async def test_run_agent_in_container_non_success_raises_not_implemented(
    monkeypatch,
) -> None:
    # Adapter returns a clarification envelope; F0 / E.2 must reject it
    # (clarification + permission handling lands in Phase F.3).
    from agent_foundry.orchestration import container_executor as ce

    def factory(*a: Any, **kw: Any) -> FakeClaudeCodeAdapter:
        return FakeClaudeCodeAdapter(
            canned_structured_output={
                "outcome": {
                    "kind": "clarification_needed",
                    "question": "what?",
                    "options": [],
                    "blocking": True,
                }
            },
        )

    monkeypatch.setattr(ce, "build_adapter", factory)

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
    with pytest.raises(NotImplementedError, match=r"Phase F\.3"):
        await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)
    assert fake_mgr.handles[0].status == "destroyed"  # finally ran
