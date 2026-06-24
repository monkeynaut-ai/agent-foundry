"""Integration test: AgentAction timeout cancels the container cleanly (#80).

The unit tests prove the compiler's per-turn deadline raises
``ConstructTimeoutError``. This test proves the *real* path: when the deadline
cancels ``run_agent_in_container`` mid-turn, the run ends in
``RunFailed(error_type="ConstructTimeoutError")`` AND no container is left
behind for the run's workspace volume.

A 1-second ``timeout_seconds`` against a real container (startup + a live
``claude`` turn take far longer than 1s) makes the cancellation deterministic.

Requires Docker and CLAUDE_CODE_OAUTH_TOKEN; fails loudly (not skips) when the
token is missing, matching the other real-Claude integration tests.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pydantic import BaseModel

from agent_foundry.agents.lifecycle import ContainerConfig, NetworkMode
from agent_foundry.constructs.models import AgentAction, ContainerReusePolicy
from agent_foundry.constructs.process import Process
from agent_foundry.orchestration.container_executor import run_agent_in_container
from agent_foundry.orchestration.run_outcome import FailureKind, RunFailed
from agent_foundry.orchestration.runner import run_process
from agent_foundry.responders.protocol import Responder, static_provider

_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


class _State(BaseModel):
    topic: str


class _Out(BaseModel):
    headline: str


class _UnusedResponder(Responder):
    async def respond(self, request, context):  # type: ignore[no-untyped-def]
        raise AssertionError(f"responder unexpectedly invoked: {request!r}")


def _instructions(_state: object) -> str:
    return "# Probe\nEmit the requested structured output.\n"


def _prompt(s: _State) -> str:
    return f"Return structured output with headline='about {s.topic}'."


@pytest.mark.integration
@pytest.mark.asyncio
async def test_timeout_cancels_container_without_orphan(tmp_path: Path, cleanup_volumes) -> None:
    oauth_token = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
    assert oauth_token  # used implicitly by run_process via os.environ

    try:
        import docker

        client = docker.from_env()
        client.ping()
    except Exception as e:
        pytest.skip(f"docker daemon unavailable: {e}")

    base_image = os.environ.get("AGENT_BASE_IMAGE", "agent-worker:latest")
    workspace_volume = f"timeout-teardown-{uuid.uuid4().hex[:8]}"
    cleanup_volumes.append(workspace_volume)

    agent = AgentAction[_State, _Out](
        name="slowpoke",
        model="claude-sonnet-4-6",
        prompt_builder=_prompt,
        instructions_provider=_instructions,
        executor=run_agent_in_container,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        container_config=ContainerConfig(network=NetworkMode.BRIDGE),
        # Far shorter than container startup + a real turn — the deadline
        # fires mid-flight, exercising cancellation/teardown.
        timeout_seconds=1,
    )
    process = Process(root=agent)

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    result = await run_process(
        process,
        initial_state=_State(topic="archipelago"),
        artifacts_dir=artifacts_dir,
        workspace_volume=workspace_volume,
        base_image_tag=base_image,
        responder_provider=static_provider(_UnusedResponder()),
        run_id=run_id,
    )

    assert isinstance(result, RunFailed)
    assert result.error_kind is FailureKind.CRASH
    assert result.error_type == "ConstructTimeoutError"

    # The cancelled turn must not orphan its container.
    residual = client.containers.list(all=True, filters={"volume": workspace_volume})
    assert not residual, f"orphan containers for {workspace_volume}: {[c.name for c in residual]}"
