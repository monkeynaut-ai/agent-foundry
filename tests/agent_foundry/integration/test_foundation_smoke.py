"""Foundation smoke test — proves base Agent Container image + ContainerManager +
host-driven `docker exec` of `claude --json-schema` + stream-json
parsing + AgentTurnEnvelope validation work end-to-end against real
Claude Code. If this fails, the orchestration stack cannot run.

This test exercises the exact transport the container executor uses
(docker exec). It does not exercise the in-container adapter or WS
server — those are legacy paths retained for docker_worker/ agents.
"""

from __future__ import annotations

import contextlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv
from pydantic import BaseModel

from agent_foundry.agents.agent_turn_envelope import AgentTurnEnvelope
from agent_foundry.agents.lifecycle import ContainerConfig, ContainerManager, NetworkMode
from agent_foundry.agents.schema_tools import to_claude_code_schema

# Load .env from the repo root so CLAUDE_CODE_OAUTH_TOKEN is available
# when running via `pdm test-integration`.
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


class Ping(BaseModel):
    echoed: str


@pytest.mark.integration
def test_foundation_smoke_real_claude_code(cleanup_volumes) -> None:
    # Fail loudly — not skip — when the OAuth token is missing.
    oauth_token = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]

    # Only skip on Docker unavailability.
    try:
        import docker

        client = docker.from_env()
        client.ping()
    except Exception as e:
        pytest.skip(f"docker daemon unavailable: {e}")

    base_image = os.environ.get("AGENT_BASE_IMAGE", "agent-worker:latest")
    workspace_volume = f"foundation-smoke-{uuid.uuid4().hex[:8]}"
    cleanup_volumes.append(workspace_volume)

    manager = ContainerManager(client=client, default_image=base_image)
    schema = to_claude_code_schema(AgentTurnEnvelope[Ping])

    role_instructions_path = "/home/claude/role-instructions.md"
    role_instructions = (
        "# Foundation smoke test role\n\n"
        "You are a probe used by Agent Foundry's foundation smoke test. "
        "When asked, emit exactly the structured output the caller requests.\n"
    )

    handle = manager.create_container(
        workspace_volume=workspace_volume,
        # Real `claude` needs egress to reach the Anthropic API; opt in.
        constraints=ContainerConfig(network=NetworkMode.BRIDGE),
        extra_env={
            "CLAUDE_CODE_OAUTH_TOKEN": oauth_token,
            "AGENT_HOST_DRIVEN": "1",
            "AGENT_ROLE_INSTRUCTIONS_PATH": role_instructions_path,
        },
    )
    try:
        # Inject role instructions before starting so the entrypoint's
        # append block has something to work with (matching the
        # AgentContainerRegistry flow).
        manager.write_file_to_container(handle, role_instructions_path, role_instructions)
        manager.start(handle)

        prompt = "Return structured output with echoed='foo'."
        exec_cmd = [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--json-schema",
            json.dumps(schema),
        ]
        # Wait for the container's Docker HEALTHCHECK to report `healthy`.
        # The base image's HEALTHCHECK polls for `/tmp/.container-ready`,
        # which the entrypoint touches after all setup (auth, lockdown,
        # role-instructions append, LSP plugin install, product-init)
        # completes. This is the signal that the container is ready to
        # receive `docker exec` calls.
        import time as _time

        deadline = _time.monotonic() + 90.0
        last_status: str | None = None
        while _time.monotonic() < deadline:
            handle._container.reload()
            health = handle._container.attrs.get("State", {}).get("Health", {}) or {}
            last_status = health.get("Status")
            if last_status == "healthy":
                break
            if last_status == "unhealthy":
                raise AssertionError(
                    f"container reported unhealthy: health={health!r}; "
                    f"logs={handle._container.logs(tail=40).decode(errors='replace')}"
                )
            _time.sleep(0.25)
        else:
            raise AssertionError(
                f"container did not become healthy within 90s "
                f"(last_status={last_status!r}); "
                f"logs={handle._container.logs(tail=40).decode(errors='replace')}"
            )

        exit_code, output = handle._container.exec_run(exec_cmd, demux=False, user="claude")
        if exit_code != 0:
            container_logs = handle._container.logs(tail=80).decode(errors="replace")
            raise AssertionError(
                f"claude exec failed (exit={exit_code}):\n"
                f"stdout/stderr: {output.decode(errors='replace')}\n\n"
                f"container logs: {container_logs}"
            )

        structured: dict[str, Any] | None = None
        for raw_line in output.decode().splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("type") == "assistant":
                for block in evt.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use" and block.get("name") == "StructuredOutput":
                        structured = block.get("input")
                        break

        assert structured is not None, "no StructuredOutput tool use captured"
        envelope = AgentTurnEnvelope[Ping].model_validate(structured)
        assert envelope.outcome.kind == "success"
        assert isinstance(envelope.outcome.payload, Ping)
        assert envelope.outcome.payload.echoed  # non-empty
    finally:
        with contextlib.suppress(Exception):
            manager.stop(handle, timeout=5)
        manager.destroy(handle)
