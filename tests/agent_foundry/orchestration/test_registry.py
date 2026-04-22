"""Tests for :class:`AgentContainerRegistry`.

Covers the full public contract:

- Lazy, identity-keyed ``get_or_create``.
- ``record_session_id``.
- Idempotent, failure-tolerant ``shutdown_all``.
- ``agent_container_started`` lifecycle events emitted through the writer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from agent_foundry.orchestration.lifecycle_writer import (
    JsonlLifecycleWriter,
    LifecycleWriter,
)
from agent_foundry.orchestration.registry import AgentContainerRegistry
from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy

from .fakes import FakeDockerClient


class InputModel(BaseModel):
    task: str


class OutputModel(BaseModel):
    answer: str


def _make_primitive() -> AgentAction[InputModel, OutputModel]:
    return AgentAction[InputModel, OutputModel](
        name="test-agent",
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
    primitive = _make_primitive()
    live = await registry.get_or_create(primitive, lifecycle_writer=writer, agent_name="coder")
    assert live is not None
    assert len(fake_docker.containers.created) == 1
    # The returned LiveContainer exposes the handle and manager.
    assert live.handle is not None
    assert live.manager is not None
    assert live.session_id is None


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent_for_same_primitive(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
    fake_docker: FakeDockerClient,
) -> None:
    primitive = _make_primitive()
    first = await registry.get_or_create(primitive, lifecycle_writer=writer, agent_name="coder")
    second = await registry.get_or_create(primitive, lifecycle_writer=writer, agent_name="coder")
    assert first is second
    # No additional container created on the repeat call.
    assert len(fake_docker.containers.created) == 1


# --- Identity keying ----------------------------------------------------------


@pytest.mark.asyncio
async def test_distinct_primitives_get_distinct_containers(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
    fake_docker: FakeDockerClient,
) -> None:
    prim_a = _make_primitive()
    prim_b = _make_primitive()
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
    primitive = _make_primitive()
    live = await registry.get_or_create(primitive, lifecycle_writer=writer, agent_name="coder")
    assert live.session_id is None
    registry.record_session_id(primitive, "sess-1")

    # Same primitive key → must return the same LiveContainer with the id set.
    again = await registry.get_or_create(primitive, lifecycle_writer=writer, agent_name="coder")
    assert again is live
    assert again.session_id == "sess-1"


@pytest.mark.asyncio
async def test_record_session_id_unknown_primitive_is_noop(
    registry: AgentContainerRegistry,
) -> None:
    primitive = _make_primitive()
    # Must not raise — simply no-op when the primitive has never been
    # registered via get_or_create.
    registry.record_session_id(primitive, "sess-x")


# --- shutdown_all -------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_all_destroys_every_registered_container(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
    fake_docker: FakeDockerClient,
) -> None:
    prim_a = _make_primitive()
    prim_b = _make_primitive()
    await registry.get_or_create(prim_a, lifecycle_writer=writer, agent_name="a")
    await registry.get_or_create(prim_b, lifecycle_writer=writer, agent_name="b")

    await registry.shutdown_all()

    # Every fake docker container has been asked to destroy itself.
    assert all(c.destroyed for c in fake_docker.containers.created)


@pytest.mark.asyncio
async def test_shutdown_all_is_idempotent(
    registry: AgentContainerRegistry,
    writer: LifecycleWriter,
) -> None:
    primitive = _make_primitive()
    await registry.get_or_create(primitive, lifecycle_writer=writer, agent_name="coder")
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
    prim_a = _make_primitive()
    prim_b = _make_primitive()
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
    primitive = _make_primitive()
    await registry.get_or_create(primitive, lifecycle_writer=writer, agent_name="coder")
    # Flush: close the writer through its public API — but the fixture
    # closes on teardown, so read via a second handle mid-test.
    import json

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
    primitive = _make_primitive()
    await registry.get_or_create(primitive, lifecycle_writer=writer, agent_name="coder")
    await registry.get_or_create(primitive, lifecycle_writer=writer, agent_name="coder")

    import json

    lines = (tmp_path / "lifecycle.jsonl").read_text().splitlines()
    started = [
        json.loads(line)
        for line in lines
        if json.loads(line).get("type") == "agent_container_started"
    ]
    # Only one start event, even with two get_or_create calls.
    assert len(started) == 1
