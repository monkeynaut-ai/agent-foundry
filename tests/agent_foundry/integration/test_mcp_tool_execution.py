"""Integration test: MCP tool execution via AgentAction.

Verifies the full path from declaring an MCP server on AgentAction through
to Claude Code loading it, calling a tool, and returning the result in
structured output.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pydantic import BaseModel

from agent_foundry.agents.lifecycle import ContainerConfig, NetworkMode
from agent_foundry.constructs.mcp import StdioMcpServer
from agent_foundry.constructs.models import AgentAction, ContainerReusePolicy
from agent_foundry.constructs.process import Process
from agent_foundry.orchestration.container_executor import run_agent_in_container
from agent_foundry.orchestration.run_outcome import RunCompleted
from agent_foundry.orchestration.runner import run_process
from agent_foundry.responders.models import (
    ResponderContext,
    ResponderRequest,
    ResponderResponse,
)
from agent_foundry.responders.protocol import Responder, static_provider

_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")

# Minimal MCP stdio echo server using bash + jq (python3 not available in container).
_ECHO_SERVER_SCRIPT = """\
while IFS= read -r line; do
  [ -z "${line// }" ] && continue
  method=$(printf '%s' "$line" | jq -r '.method // ""')
  id=$(printf '%s' "$line" | jq '.id // null')
  [ "$id" = "null" ] && continue
  case "$method" in
    initialize)
      printf '%s' "$line" | jq -c '{jsonrpc:"2.0",id:.id,result:{protocolVersion:"2024-11-05",capabilities:{tools:{}},serverInfo:{name:"echo",version:"0.1.0"}}}'
      ;;
    "tools/list")
      printf '%s' "$line" | jq -c '{jsonrpc:"2.0",id:.id,result:{tools:[{name:"echo",description:"Echo the message back unchanged.",inputSchema:{type:"object",properties:{message:{type:"string",description:"Text to echo."}},required:["message"]}}]}}'
      ;;
    "tools/call")
      printf '%s' "$line" | jq -c '{jsonrpc:"2.0",id:.id,result:{content:[{type:"text",text:(.params.arguments.message // "")}]}}'
      ;;
    *)
      printf '%s' "$line" | jq -c '{jsonrpc:"2.0",id:.id,error:{code:-32601,message:"Method not found"}}'
      ;;
  esac
done
"""

_ECHO_WORD = "archipelago"


class _Input(BaseModel):
    word: str


class _Output(BaseModel):
    echoed_word: str


class _FailResponder(Responder):
    async def respond(
        self, request: ResponderRequest, context: ResponderContext
    ) -> ResponderResponse:
        raise AssertionError(f"responder unexpectedly called: {request!r}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_calls_stdio_mcp_tool_and_returns_result(
    tmp_path: Path, cleanup_volumes
) -> None:
    """MCP server declared on AgentAction is loaded by Claude Code and the
    agent can call its tools, with results surfaced in structured output."""

    oauth_token = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
    assert oauth_token

    try:
        import docker

        client = docker.from_env()
        client.ping()
    except Exception as e:
        pytest.skip(f"docker daemon unavailable: {e}")

    base_image = os.environ.get("AGENT_BASE_IMAGE", "agent-worker:latest")
    workspace_volume = f"mcp-echo-{uuid.uuid4().hex[:8]}"
    cleanup_volumes.append(workspace_volume)

    def _prompt(s: _Input) -> str:
        return (
            f"Call the 'echo' tool on the MCP server named 'echo' with message='{s.word}'. "
            f"Return structured output with echoed_word set to exactly the text the tool returned."
        )

    def _instructions(_s: _Input) -> str:
        return (
            "# Role — MCP echo probe\n\n"
            "You are a probe used by Agent Foundry's MCP integration test. "
            "Call the specified MCP tool and return the result as structured output.\n"
        )

    agent = AgentAction[_Input, _Output](
        name="echo-probe",
        model="claude-haiku-4-5-20251001",
        prompt_builder=_prompt,
        instructions_provider=_instructions,
        executor=run_agent_in_container,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        mcp_servers={"echo": StdioMcpServer(command="bash", args=["-c", _ECHO_SERVER_SCRIPT])},
        skip_permissions=True,
        # Real claude needs egress to reach the Anthropic API.
        container_config=ContainerConfig(network=NetworkMode.BRIDGE),
    )

    result = await run_process(
        Process(root=agent),
        initial_state=_Input(word=_ECHO_WORD),
        artifacts_dir=tmp_path / "artifacts",
        workspace_volume=workspace_volume,
        base_image_tag=base_image,
        responder_provider=static_provider(_FailResponder()),
    )

    assert isinstance(result, RunCompleted)
    output = result.output
    assert isinstance(output, _Output)
    assert output.echoed_word == _ECHO_WORD
