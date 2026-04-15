"""Foundation smoke test — proves base ACP image + ContainerManager +
host-driven `docker exec` of `claude --json-schema` + stream-json
parsing + AgentTurnEnvelope validation work end-to-end against real
Claude Code. If this fails, Plan 2 cannot proceed.

This test exercises the exact transport Plan 2's executor uses
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

from agent_foundry.acp.agent_turn_envelope import AgentTurnEnvelope
from agent_foundry.acp.container import ContainerManager
from agent_foundry.acp.schema_tools import to_claude_code_schema

# Load .env from the repo root so CLAUDE_CODE_OAUTH_TOKEN is available
# when running via `pdm test-integration`.
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


class Ping(BaseModel):
    echoed: str


@pytest.mark.integration
def test_foundation_smoke_real_claude_code() -> None:
    # Fail loudly — not skip — when the OAuth token is missing.
    oauth_token = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]

    # Only skip on Docker unavailability.
    try:
        import docker

        client = docker.from_env()
        client.ping()
    except Exception as e:
        pytest.skip(f"docker daemon unavailable: {e}")

    base_image = os.environ.get("ACP_BASE_IMAGE", "acp-cc-worker:latest")
    workspace_volume = f"foundation-smoke-{uuid.uuid4().hex[:8]}"

    manager = ContainerManager(client=client, default_image=base_image)
    schema = to_claude_code_schema(AgentTurnEnvelope[Ping])

    role_instructions_path = "/home/claude/role-instructions.md"
    role_instructions = (
        "# Foundation smoke test role\n\n"
        "You are a probe used by Agent Foundry's Plan 2 foundation smoke test. "
        "When asked, emit exactly the structured output the caller requests.\n"
    )

    handle = manager.create_container(
        workspace_volume=workspace_volume,
        extra_env={
            "CLAUDE_CODE_OAUTH_TOKEN": oauth_token,
            "ACP_HOST_DRIVEN": "1",
            "ACP_ROLE_INSTRUCTIONS_PATH": role_instructions_path,
        },
    )
    try:
        # Inject role instructions before starting so the entrypoint's
        # append block has something to work with (matching Plan 2's
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
        # Give the entrypoint time to finish setup (plugin install, etc.)
        import time as _time

        _time.sleep(2)
        handle._container.reload()
        assert handle._container.status == "running", (
            f"container not running; status={handle._container.status}; "
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
