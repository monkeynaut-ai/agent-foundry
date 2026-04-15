"""F0 end-to-end: build a real AgentAction, construct the context
manually (no run_primitive_plan wiring yet — that's Phase G.2), and
drive run_agent_in_container against real Claude Code in a real
container.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv
from pydantic import BaseModel

from agent_foundry.orchestration import container_executor
from agent_foundry.orchestration.container_executor import run_agent_in_container
from agent_foundry.orchestration.registry import AgentContainerRegistry, LiveContainer
from agent_foundry.orchestration.run_context import (
    AgentRunContext,
    NoOpLifecycleWriter,
)
from agent_foundry.primitives.models import (
    AgentAction,
    ContainerReusePolicy,
    StructuredOutputChannel,
)

# Load .env from the repo root so CLAUDE_CODE_OAUTH_TOKEN is available
# when running via `pdm test-integration`.
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


class AnalysisInput(BaseModel):
    topic: str


class AnalysisOutput(BaseModel):
    headline: str


class _HostDrivenAdapter:
    """Minimal host-side Claude Code driver for F0 end-to-end.

    Runs ``claude -p <prompt> --output-format stream-json --verbose
    --json-schema <schema>`` inside the given container via docker
    exec (as user ``claude``) and returns the first StructuredOutput
    tool-use input parsed from the stream. This is a test-only
    stand-in for the Phase F.3 ExecRunDriver.
    """

    def __init__(self, live: LiveContainer) -> None:
        self._live = live

    async def run_turn(
        self,
        *,
        prompt: str,
        json_schema: dict[str, Any],
        resume_session_id: str | None = None,
    ) -> dict[str, Any]:
        import asyncio

        def _do_exec() -> dict[str, Any]:
            cmd = [
                "claude",
                "-p",
                prompt,
                "--output-format",
                "stream-json",
                "--verbose",
                "--json-schema",
                json.dumps(json_schema),
            ]
            exit_code, output = self._live.handle._container.exec_run(
                cmd, demux=False, user="claude"
            )
            if exit_code != 0:
                logs = self._live.handle._container.logs(tail=80).decode(errors="replace")
                raise AssertionError(
                    f"claude exec failed (exit={exit_code}):\n"
                    f"stdout/stderr: {output.decode(errors='replace')}\n\n"
                    f"container logs: {logs}"
                )
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
                        if (
                            block.get("type") == "tool_use"
                            and block.get("name") == "StructuredOutput"
                        ):
                            return block.get("input")
            raise AssertionError("no StructuredOutput tool use captured")

        return await asyncio.to_thread(_do_exec)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_f0_end_to_end_real_claude_code(monkeypatch) -> None:
    oauth_token = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]

    try:
        import docker

        client = docker.from_env()
        client.ping()
    except Exception as e:
        pytest.skip(f"docker daemon unavailable: {e}")

    from agent_foundry.acp.container import ContainerManager

    base_image = os.environ.get("ACP_BASE_IMAGE", "acp-cc-worker:latest")
    workspace_volume = f"f0-e2e-{uuid.uuid4().hex[:8]}"
    manager = ContainerManager(client=client, default_image=base_image)
    registry = AgentContainerRegistry(
        manager=manager,
        base_image_tag=base_image,
        workspace_volume=workspace_volume,
    )
    ctx = AgentRunContext(
        run_id=f"run-{uuid.uuid4().hex[:8]}",
        container_registry=registry,
        lifecycle_writer=NoOpLifecycleWriter(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": oauth_token},
    )

    # Inject the F0 host-driven adapter in place of the Phase F.3 stub.
    monkeypatch.setattr(
        container_executor,
        "build_adapter",
        lambda live: _HostDrivenAdapter(live),
    )

    primitive = AgentAction[AnalysisInput, AnalysisOutput](
        prompt_builder=lambda s: f"Write a one-line headline about {s.topic}.",
        instructions_provider=lambda: (
            "You are a headline writer. Return structured output with a "
            "single `headline` field. Be concise."
        ),
        executor=run_agent_in_container,
        response_channel=StructuredOutputChannel(),
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    )

    result = await run_agent_in_container(
        primitive=primitive,
        prompt=primitive.prompt_builder(AnalysisInput(topic="cats")),
        run_ctx=ctx,
    )
    assert isinstance(result, AnalysisOutput)
    assert result.headline.strip()
