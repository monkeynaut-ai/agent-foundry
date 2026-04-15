from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_foundry.orchestration.registry import AgentContainerRegistry

from .fakes import FakeContainerManager


@pytest.mark.asyncio
async def test_create_for_invocation_writes_instructions_and_starts() -> None:
    fake_mgr = FakeContainerManager()
    registry = AgentContainerRegistry(
        manager=fake_mgr,
        base_image_tag="agent-foundry-base:test",
        workspace_volume="vol-1",
    )
    primitive = MagicMock()
    live = await registry.create_for_invocation(
        primitive,
        oauth_token="tok",
        instructions_text="# agent role\nBe precise.",
    )
    assert live.handle.status == "running"
    assert live.handle.env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok"
    assert live.handle.env["ACP_ROLE_INSTRUCTIONS_PATH"]
    written_path = live.handle.env["ACP_ROLE_INSTRUCTIONS_PATH"]
    assert live.handle.files[written_path] == "# agent role\nBe precise."


@pytest.mark.asyncio
async def test_destroy_marks_handle_destroyed() -> None:
    fake_mgr = FakeContainerManager()
    registry = AgentContainerRegistry(
        manager=fake_mgr,
        base_image_tag="agent-foundry-base:test",
        workspace_volume="vol-2",
    )
    primitive = MagicMock()
    live = await registry.create_for_invocation(primitive, oauth_token="t", instructions_text="x")
    await registry.destroy(live)
    assert live.handle.status == "destroyed"
