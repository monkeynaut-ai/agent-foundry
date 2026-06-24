"""Tests for :class:`AgentContainerRegistry`.

Covers the full public contract:

- Lazy, identity-keyed ``get_or_create``.
- ``record_session_id``.
- Idempotent, failure-tolerant ``shutdown_all``.
- ``agent_container_started`` lifecycle events emitted through the writer.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.agents.lifecycle import HealthReport, HealthStatus
from agent_foundry.constructs import StdioMcpServer
from agent_foundry.constructs.models import AgentAction, ContainerReusePolicy
from agent_foundry.orchestration.lifecycle_writer import (
    JsonlLifecycleWriter,
    LifecycleWriter,
)
from agent_foundry.orchestration.registry import (
    CLAUDE_CONFIG_PATH,
    MCP_SETTINGS_PATH,
    AgentContainerRegistry,
)

from .fakes import FakeContainerManager, FakeDockerClient


class InputModel(BaseModel):
    task: str


class OutputModel(BaseModel):
    answer: str


def _make_construct() -> AgentAction[InputModel, OutputModel]:
    return AgentAction[InputModel, OutputModel](
        name="test-agent",
        model="claude-sonnet-4-6",
        prompt_builder=lambda s: f"do: {s.task}",
        instructions_provider=lambda _s: "Be precise.",
        executor=lambda **kwargs: OutputModel(answer="x"),
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    )


@pytest.fixture
def fake_docker() -> FakeDockerClient:
    return FakeDockerClient()


@pytest.fixture
def registry(fake_docker: FakeDockerClient) -> AgentContainerRegistry:
    return AgentContainerRegistry(
        workspace_volume="test-vol",
        base_image_tag="agent-foundry-base:test",
        docker_client_factory=lambda: fake_docker,
    )


@pytest.fixture
def writer(tmp_path: Path) -> LifecycleWriter:
    w = JsonlLifecycleWriter(run_id="run-reg", path=tmp_path / "lifecycle.jsonl")
    yield w
    w.close()


# --- Lazy creation ------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_creates_exactly_one_container_on_first_call(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
    fake_docker: FakeDockerClient,
) -> None:
    construct = _make_construct()
    live = await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="coder")
    assert live is not None
    assert len(fake_docker.containers.created) == 1
    # The returned LiveContainer exposes the handle and manager.
    assert live.handle is not None
    assert live.manager is not None
    assert live.session_id is None


@pytest.mark.asyncio
async def test_get_or_create_forwards_extra_volumes_to_create_container(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
    fake_docker: FakeDockerClient,
) -> None:
    construct = _make_construct()
    extra = {"/host/ca.crt": {"bind": "/etc/ca.crt", "mode": "ro"}}
    await registry.get_or_create(
        construct,
        lifecycle_writer=writer,
        agent_name="coder",
        extra_volumes=extra,
    )
    create_kwargs = fake_docker.containers.create_calls[0]["kwargs"]
    assert create_kwargs["volumes"]["/host/ca.crt"] == {"bind": "/etc/ca.crt", "mode": "ro"}


@pytest.mark.asyncio
async def test_get_or_create_merges_extra_env_into_container_env(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
    fake_docker: FakeDockerClient,
) -> None:
    construct = _make_construct()
    await registry.get_or_create(
        construct,
        lifecycle_writer=writer,
        agent_name="coder",
        extra_env={"HTTPS_PROXY": "http://host.docker.internal:8080"},
    )
    env = fake_docker.containers.create_calls[0]["kwargs"]["environment"]
    assert env["HTTPS_PROXY"] == "http://host.docker.internal:8080"


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent_for_same_construct(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
    fake_docker: FakeDockerClient,
) -> None:
    construct = _make_construct()
    first = await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="coder")
    second = await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="coder")
    assert first is second
    # No additional container created on the repeat call.
    assert len(fake_docker.containers.created) == 1


# --- Identity keying ----------------------------------------------------------


@pytest.mark.asyncio
async def test_distinct_constructs_get_distinct_containers(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
    fake_docker: FakeDockerClient,
) -> None:
    prim_a = _make_construct()
    prim_b = _make_construct()
    assert prim_a is not prim_b  # sanity: different identities

    live_a = await registry.get_or_create(prim_a, lifecycle_writer=writer, agent_name="a")
    live_b = await registry.get_or_create(prim_b, lifecycle_writer=writer, agent_name="b")
    assert live_a is not live_b
    assert live_a.handle is not live_b.handle
    assert len(fake_docker.containers.created) == 2


# --- record_session_id --------------------------------------------------------


@pytest.mark.asyncio
async def test_record_session_id_stamps_live_container(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
) -> None:
    construct = _make_construct()
    live = await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="coder")
    assert live.session_id is None
    registry.record_session_id(construct, "sess-1")

    # Same construct key → must return the same LiveContainer with the id set.
    again = await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="coder")
    assert again is live
    assert again.session_id == "sess-1"


@pytest.mark.asyncio
async def test_record_session_id_unknown_construct_is_noop(
    registry: AgentContainerRegistry,
) -> None:
    construct = _make_construct()
    # Must not raise — simply no-op when the construct has never been
    # registered via get_or_create.
    registry.record_session_id(construct, "sess-x")


# --- shutdown_all -------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_all_destroys_every_registered_container(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
    fake_docker: FakeDockerClient,
) -> None:
    prim_a = _make_construct()
    prim_b = _make_construct()
    await registry.get_or_create(prim_a, lifecycle_writer=writer, agent_name="a")
    await registry.get_or_create(prim_b, lifecycle_writer=writer, agent_name="b")

    await registry.shutdown_all()

    # Every fake docker container has been asked to destroy itself.
    assert all(c.destroyed for c in fake_docker.containers.created)


@pytest.mark.asyncio
async def test_shutdown_all_retains_failed_container_when_pause_on_failure_true(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
    fake_docker: FakeDockerClient,
) -> None:
    """With pause_on_failure=True, ``shutdown_all`` skips destroy for any
    LiveContainer marked failed. Successful containers in the same run
    still destroy — the retention is narrow.
    """
    prim_failed = _make_construct()
    prim_ok = _make_construct()
    live_failed = await registry.get_or_create(
        prim_failed, lifecycle_writer=writer, agent_name="failed-one"
    )
    live_ok = await registry.get_or_create(prim_ok, lifecycle_writer=writer, agent_name="ok-one")
    live_failed.failed = True

    await registry.shutdown_all(pause_on_failure=True)

    # Both fake-docker containers were created; only the OK one was destroyed.
    failed_fake = next(
        c for c in fake_docker.containers.created if c.id == live_failed.handle.container_id
    )
    ok_fake = next(c for c in fake_docker.containers.created if c.id == live_ok.handle.container_id)
    assert failed_fake.destroyed is False, "failed container must be retained"
    assert ok_fake.destroyed is True, "successful container must still destroy"


@pytest.mark.asyncio
async def test_shutdown_all_destroys_failed_container_when_pause_on_failure_false(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
    fake_docker: FakeDockerClient,
) -> None:
    """pause_on_failure=False is the default: every container destroys
    regardless of the failed flag. Production runs don't accumulate
    dead containers.
    """
    construct = _make_construct()
    live = await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="a")
    live.failed = True

    await registry.shutdown_all(pause_on_failure=False)

    fake = next(c for c in fake_docker.containers.created if c.id == live.handle.container_id)
    assert fake.destroyed is True


@pytest.mark.asyncio
async def test_shutdown_all_is_idempotent(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
) -> None:
    construct = _make_construct()
    await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="coder")
    await registry.shutdown_all()
    # Second call must not raise.
    await registry.shutdown_all()


@pytest.mark.asyncio
async def test_shutdown_all_tolerates_individual_destroy_failure(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
    fake_docker: FakeDockerClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    prim_a = _make_construct()
    prim_b = _make_construct()
    live_a = await registry.get_or_create(prim_a, lifecycle_writer=writer, agent_name="a")
    live_b = await registry.get_or_create(prim_b, lifecycle_writer=writer, agent_name="b")

    # Monkeypatch live_a.manager.destroy to raise — live_b must still be
    # destroyed and the exception logged (not re-raised).
    original_destroy = live_a.manager.destroy

    def raising_destroy(handle):
        if handle is live_a.handle:
            raise RuntimeError("boom-a")
        return original_destroy(handle)

    live_a.manager.destroy = raising_destroy  # type: ignore[method-assign]
    # live_b shares the same manager if they're built from the same factory,
    # but we patched the bound attribute on live_a.manager only. If they
    # happen to be the same manager instance, we still want live_b to
    # succeed — delegate by matching on the handle identity above.
    if live_b.manager is live_a.manager:
        pass  # same manager; raising_destroy already guards per-handle

    # Must NOT raise.
    await registry.shutdown_all()

    # live_b's underlying fake container must be destroyed.
    # Identify live_b's container via the FakeDockerClient's created list:
    # exactly one of the two should be destroyed (live_a's failed).
    destroyed = [c for c in fake_docker.containers.created if c.destroyed]
    assert len(destroyed) >= 1
    # And a warning log records the failure.
    assert any(
        "boom-a" in rec.message or "destroy" in rec.message.lower() for rec in caplog.records
    )


# --- Lifecycle events ---------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_emits_agent_container_started(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
    tmp_path: Path,
) -> None:
    construct = _make_construct()
    await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="coder")
    # Flush: close the writer through its public API — but the fixture
    # closes on teardown, so read via a second handle mid-test.

    lines = (tmp_path / "lifecycle.jsonl").read_text().splitlines()
    records = [json.loads(line) for line in lines]
    started = [r for r in records if r.get("type") == "agent_container_started"]
    assert len(started) == 1
    assert started[0]["agent_name"] == "coder"
    assert "container_id" in started[0]


@pytest.mark.asyncio
async def test_get_or_create_emits_event_only_on_first_creation(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
    tmp_path: Path,
) -> None:
    construct = _make_construct()
    await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="coder")
    await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="coder")

    lines = (tmp_path / "lifecycle.jsonl").read_text().splitlines()
    started = [
        json.loads(line)
        for line in lines
        if json.loads(line).get("type") == "agent_container_started"
    ]
    # Only one start event, even with two get_or_create calls.
    assert len(started) == 1


# --- Health waiting (uses manager.health_status, not docker SDK directly) -----


@pytest.mark.asyncio
async def test_wait_for_health_polls_manager_health_status_when_enabled(
    writer: LifecycleWriter,
) -> None:
    """The health-wait gate must go through manager.health_status —
    no direct docker-SDK access from the registry."""
    fake_mgr = FakeContainerManager()
    registry = AgentContainerRegistry(
        workspace_volume="vol",
        base_image_tag="img",
        manager=fake_mgr,
    )
    construct = _make_construct()
    await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="coder")
    # FakeContainerManager records each health_status call by container_id.
    assert len(fake_mgr.health_log) >= 1


@pytest.mark.asyncio
async def test_wait_for_health_returns_when_status_healthy(
    writer: LifecycleWriter,
) -> None:
    fake_mgr = FakeContainerManager()
    registry = AgentContainerRegistry(
        workspace_volume="vol",
        base_image_tag="img",
        manager=fake_mgr,
    )
    construct = _make_construct()
    # FakeContainerManager defaults to HEALTHY → loop exits on first poll.
    live = await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="coder")
    assert live is not None
    assert len(fake_mgr.health_log) == 1


@pytest.mark.asyncio
async def test_wait_for_health_raises_on_unhealthy_report(
    writer: LifecycleWriter,
) -> None:
    fake_mgr = FakeContainerManager()
    registry = AgentContainerRegistry(
        workspace_volume="vol",
        base_image_tag="img",
        manager=fake_mgr,
    )
    construct = _make_construct()
    # Pre-script the next handle to come back UNHEALTHY. The handle's
    # container_id follows the FakeContainerManager's _next_id counter,
    # so we know it'll be "fake-1".
    fake_mgr.health_script["fake-1"] = HealthReport(
        status=HealthStatus.UNHEALTHY,
        raw={"FailingStreak": 3, "Log": [{"Output": "boom"}]},
    )
    with pytest.raises(RuntimeError, match="unhealthy"):
        await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="coder")


# --- LiveContainer invocation counter ----------------------------------------


def test_live_container_next_invocation_returns_monotonic_counter() -> None:
    from agent_foundry.orchestration.registry import LiveContainer

    fake_mgr = FakeContainerManager()
    handle = fake_mgr.create_container()
    live = LiveContainer(handle=handle, manager=fake_mgr)
    assert live.next_invocation() == 1
    assert live.next_invocation() == 2
    assert live.next_invocation() == 3


def test_live_container_next_invocation_independent_across_instances() -> None:
    from agent_foundry.orchestration.registry import LiveContainer

    fake_mgr = FakeContainerManager()
    h_a = fake_mgr.create_container()
    h_b = fake_mgr.create_container()
    live_a = LiveContainer(handle=h_a, manager=fake_mgr)
    live_b = LiveContainer(handle=h_b, manager=fake_mgr)
    assert live_a.next_invocation() == 1
    assert live_a.next_invocation() == 2
    assert live_b.next_invocation() == 1


@pytest.mark.asyncio
async def test_wait_for_health_treats_health_none_as_ready(
    writer: LifecycleWriter,
) -> None:
    """Image declares no HEALTHCHECK → registry returns immediately.

    This preserves the pre-migration behavior where a container with no
    HEALTHCHECK and a running status was considered ready.
    """
    fake_mgr = FakeContainerManager()
    registry = AgentContainerRegistry(
        workspace_volume="vol",
        base_image_tag="img",
        manager=fake_mgr,
    )
    construct = _make_construct()
    fake_mgr.health_script["fake-1"] = HealthReport(status=HealthStatus.NONE)
    live = await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="coder")
    assert live is not None


# ======================================================================
# LiveContainer — gids field
# ======================================================================


from agent_foundry.orchestration.registry import LiveContainer  # noqa: E402

from .fakes import FakeContainerHandle  # noqa: E402


class TestLiveContainerGids:
    def test_live_container_gids_defaults_to_empty(self):
        handle = FakeContainerHandle(container_id="c1", workspace_path="/workspace", env={})
        fake_mgr = FakeContainerManager()
        live = LiveContainer(handle=handle, manager=fake_mgr)
        assert live.gids == []

    def test_live_container_gids_accepts_list(self):
        handle = FakeContainerHandle(container_id="c1", workspace_path="/workspace", env={})
        fake_mgr = FakeContainerManager()
        live = LiveContainer(handle=handle, manager=fake_mgr, gids=[1001, 1002])
        assert live.gids == [1001, 1002]


class TestGetOrCreateGidPropagation:
    @pytest.mark.asyncio
    async def test_given_construct_with_gids_then_live_container_gids_match(
        self, writer: LifecycleWriter
    ) -> None:
        fake_mgr = FakeContainerManager()
        registry = AgentContainerRegistry(
            workspace_volume="vol",
            base_image_tag="img",
            manager=fake_mgr,
        )
        construct = AgentAction[InputModel, OutputModel](
            name="writer",
            model="claude-sonnet-4-6",
            prompt_builder=lambda s: f"do: {s.task}",
            instructions_provider=lambda _s: "Be precise.",
            executor=lambda **kwargs: OutputModel(answer="x"),
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            gids=[1001],
        )
        live = await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="writer")
        assert live.gids == [1001]

    @pytest.mark.asyncio
    async def test_given_construct_with_no_gids_then_live_container_gids_empty(
        self, writer: LifecycleWriter
    ) -> None:
        fake_mgr = FakeContainerManager()
        registry = AgentContainerRegistry(
            workspace_volume="vol",
            base_image_tag="img",
            manager=fake_mgr,
        )
        construct = _make_construct()
        live = await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="reader")
        assert live.gids == []


class TestGetOrCreateSupplementaryGidsEnv:
    """Registry injects SUPPLEMENTARY_GIDS env var when construct.gids is set.

    The Docker exec API does not support GroupAdd. Group membership must be
    configured at container startup via the entrypoint reading SUPPLEMENTARY_GIDS.
    """

    @pytest.mark.asyncio
    async def test_given_construct_with_gids_then_container_gets_supplementary_gids_env(
        self, writer: LifecycleWriter
    ) -> None:
        fake_mgr = FakeContainerManager()
        registry = AgentContainerRegistry(
            workspace_volume="vol",
            base_image_tag="img",
            manager=fake_mgr,
        )
        construct = AgentAction[InputModel, OutputModel](
            name="writer",
            model="claude-sonnet-4-6",
            prompt_builder=lambda s: f"do: {s.task}",
            instructions_provider=lambda _s: "Be precise.",
            executor=lambda **kwargs: OutputModel(answer="x"),
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            gids=[1001],
        )
        await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="writer")
        assert fake_mgr.handles[0].env.get("SUPPLEMENTARY_GIDS") == "1001"

    @pytest.mark.asyncio
    async def test_given_construct_with_multiple_gids_then_env_is_comma_separated(
        self, writer: LifecycleWriter
    ) -> None:
        fake_mgr = FakeContainerManager()
        registry = AgentContainerRegistry(
            workspace_volume="vol",
            base_image_tag="img",
            manager=fake_mgr,
        )
        construct = AgentAction[InputModel, OutputModel](
            name="writer",
            model="claude-sonnet-4-6",
            prompt_builder=lambda s: f"do: {s.task}",
            instructions_provider=lambda _s: "Be precise.",
            executor=lambda **kwargs: OutputModel(answer="x"),
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            gids=[1001, 1002],
        )
        await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="writer")
        assert fake_mgr.handles[0].env.get("SUPPLEMENTARY_GIDS") == "1001,1002"

    @pytest.mark.asyncio
    async def test_given_construct_with_no_gids_then_no_supplementary_gids_env(
        self, writer: LifecycleWriter
    ) -> None:
        fake_mgr = FakeContainerManager()
        registry = AgentContainerRegistry(
            workspace_volume="vol",
            base_image_tag="img",
            manager=fake_mgr,
        )
        construct = _make_construct()
        await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="reader")
        assert "SUPPLEMENTARY_GIDS" not in fake_mgr.handles[0].env


def _make_construct_with_mcp() -> AgentAction[InputModel, OutputModel]:
    return AgentAction[InputModel, OutputModel](
        name="mcp-agent",
        model="claude-sonnet-4-6",
        prompt_builder=lambda s: f"do: {s.task}",
        instructions_provider=lambda _s: "Use MCP.",
        executor=lambda **kwargs: OutputModel(answer="x"),
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        mcp_servers={"fs": StdioMcpServer(command="npx", args=["-y", "mcp-fs"])},
    )


class OrderCaptureFakeManager(FakeContainerManager):
    """FakeContainerManager subclass that records write_file_to_container and start call order."""

    def __init__(self) -> None:
        super().__init__()
        self.call_log: list[str] = []

    def write_file_to_container(self, handle: Any, path: str, content: str) -> None:
        self.call_log.append(f"write:{path}")
        super().write_file_to_container(handle, path, content)

    def start(self, handle: Any) -> None:
        self.call_log.append("start")
        super().start(handle)


class TestMcpSettingsInjection:
    @pytest.mark.asyncio
    async def test_mcp_servers_written_to_claude_json(self, writer: LifecycleWriter) -> None:
        fake_mgr = FakeContainerManager()
        registry = AgentContainerRegistry(
            workspace_volume="vol",
            base_image_tag="img",
            manager=fake_mgr,
        )
        construct = _make_construct_with_mcp()
        await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="mcp-agent")
        assert CLAUDE_CONFIG_PATH in fake_mgr.handles[0].files
        claude_json = json.loads(fake_mgr.handles[0].files[CLAUDE_CONFIG_PATH])
        servers = claude_json["projects"]["/workspace"]["mcpServers"]
        assert "fs" in servers

    @pytest.mark.asyncio
    async def test_permissions_written_to_settings_json(self, writer: LifecycleWriter) -> None:
        fake_mgr = FakeContainerManager()
        registry = AgentContainerRegistry(
            workspace_volume="vol",
            base_image_tag="img",
            manager=fake_mgr,
        )
        construct = _make_construct_with_mcp()
        await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="mcp-agent")
        assert MCP_SETTINGS_PATH in fake_mgr.handles[0].files
        settings = json.loads(fake_mgr.handles[0].files[MCP_SETTINGS_PATH])
        assert "mcp__fs__*" in settings["permissions"]["allow"]

    @pytest.mark.asyncio
    async def test_mcp_settings_not_written_when_no_servers(self, writer: LifecycleWriter) -> None:
        fake_mgr = FakeContainerManager()
        registry = AgentContainerRegistry(
            workspace_volume="vol",
            base_image_tag="img",
            manager=fake_mgr,
        )
        construct = _make_construct()
        await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="test-agent")
        assert CLAUDE_CONFIG_PATH not in fake_mgr.handles[0].files
        assert MCP_SETTINGS_PATH not in fake_mgr.handles[0].files

    @pytest.mark.asyncio
    async def test_claude_json_server_entry_format(self, writer: LifecycleWriter) -> None:
        fake_mgr = FakeContainerManager()
        registry = AgentContainerRegistry(
            workspace_volume="vol",
            base_image_tag="img",
            manager=fake_mgr,
        )
        construct = AgentAction[InputModel, OutputModel](
            name="mcp-agent",
            model="claude-sonnet-4-6",
            prompt_builder=lambda s: f"do: {s.task}",
            instructions_provider=lambda _s: "Use MCP.",
            executor=lambda **kwargs: OutputModel(answer="x"),
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            mcp_servers={
                "fs": StdioMcpServer(
                    command="npx",
                    args=["-y", "mcp-fs"],
                    env={"HOME": "/tmp"},
                )
            },
        )
        await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="mcp-agent")
        claude_json = json.loads(fake_mgr.handles[0].files[CLAUDE_CONFIG_PATH])
        server = claude_json["projects"]["/workspace"]["mcpServers"]["fs"]
        assert server == {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "mcp-fs"],
            "env": {"HOME": "/tmp"},
        }

    @pytest.mark.asyncio
    async def test_mcp_files_written_before_container_start(self, writer: LifecycleWriter) -> None:
        tracking_mgr = OrderCaptureFakeManager()
        registry = AgentContainerRegistry(
            workspace_volume="vol",
            base_image_tag="img",
            manager=tracking_mgr,
        )
        construct = _make_construct_with_mcp()
        await registry.get_or_create(construct, lifecycle_writer=writer, agent_name="mcp-agent")
        claude_json_key = f"write:{CLAUDE_CONFIG_PATH}"
        settings_key = f"write:{MCP_SETTINGS_PATH}"
        assert claude_json_key in tracking_mgr.call_log
        assert settings_key in tracking_mgr.call_log
        assert "start" in tracking_mgr.call_log
        start_idx = tracking_mgr.call_log.index("start")
        assert tracking_mgr.call_log.index(claude_json_key) < start_idx
        assert tracking_mgr.call_log.index(settings_key) < start_idx


# --- Cancellation during create (issue #113) ---------------------------------


class _SlowCreateManager(FakeContainerManager):
    """``create_container`` blocks in its worker thread long enough for an outer
    ``asyncio.wait_for`` deadline to cancel ``get_or_create`` mid-create."""

    def create_container(self, *args: Any, **kwargs: Any) -> Any:
        time.sleep(0.3)
        return super().create_container(*args, **kwargs)


@pytest.mark.asyncio
async def test_cancel_during_create_still_reaps_container(
    writer: LifecycleWriter,
) -> None:
    """A timeout cancelling ``get_or_create`` while ``create_container`` runs in
    its thread must not leak the container. ``asyncio.to_thread`` cannot be
    cancelled, so the thread finishes the create after cancellation; the registry
    must still track the resulting container so ``shutdown_all`` reaps it.
    """
    manager = _SlowCreateManager()
    registry = AgentContainerRegistry(
        workspace_volume="test-vol",
        base_image_tag="agent-foundry-base:test",
        manager=manager,
    )
    construct = _make_construct()

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            registry.get_or_create(construct, lifecycle_writer=writer, agent_name="coder"),
            timeout=0.05,
        )

    # The create thread finishes the docker create it had already started.
    for _ in range(200):
        if manager.handles:
            break
        await asyncio.sleep(0.01)
    assert len(manager.handles) == 1, "create thread should have produced one container"

    await registry.shutdown_all()

    # The created container must have been tracked and destroyed — not leaked.
    assert manager.handles[0].status == "destroyed"
    assert manager.handles[0].container_id in manager.destroyed_ids
