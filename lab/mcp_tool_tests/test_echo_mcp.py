# ruff: noqa: E501
"""Lab: MCP tool call end-to-end test.

Proves that an AgentAction can declare an MCP server and have Claude Code
call tools from it during a turn, with results flowing back into the LLM
and appearing in the final StructuredOutput.

The MCP server is a minimal Python echo server delivered inline via
``python3 -c "..."``.  No external binaries, no network — everything runs
inside the agent container.

Run:
    ./lab/mcp_tool_tests/run.sh
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pydantic import BaseModel

from agent_foundry.orchestration.container_executor import run_agent_in_container
from agent_foundry.orchestration.runner import run_primitive_plan
from agent_foundry.primitives.mcp import StdioMcpServer
from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy
from agent_foundry.primitives.plan import PrimitivePlan
from agent_foundry.responders.models import (
    ResponderContext,
    ResponderRequest,
    ResponderResponse,
)
from agent_foundry.responders.protocol import Responder, static_provider

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")

# ---------------------------------------------------------------------------
# Minimal MCP stdio echo server (bash + jq)
#
# The agent container has bash and jq but not python3. Implements just
# enough of JSON-RPC 2.0 / MCP to satisfy Claude Code:
#   initialize   → server info + capabilities
#   tools/list   → one tool: echo(message: str) -> str
#   tools/call   → returns the message unchanged
#   notifications (no id) → silently ignored
# ---------------------------------------------------------------------------
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

ECHO_WORD = "archipelago"


# ---------------------------------------------------------------------------
# State models
# ---------------------------------------------------------------------------


class EchoInput(BaseModel):
    word: str


class EchoOutput(BaseModel):
    echoed_word: str


# ---------------------------------------------------------------------------
# Responder — should never be called for this happy-path test
# ---------------------------------------------------------------------------


class _FailResponder(Responder):
    async def respond(
        self, request: ResponderRequest, context: ResponderContext
    ) -> ResponderResponse:
        raise AssertionError(f"responder unexpectedly called: {request!r}")


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_calls_mcp_echo_tool() -> None:
    """Agent declares an MCP echo server, calls it during its turn, and
    returns the echoed value in structured output."""

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

    def _prompt(s: EchoInput) -> str:
        return (
            f"You have access to an MCP server named 'echo' with one tool also called 'echo'. "
            f"Call the echo tool with message='{s.word}'. "
            f"Return structured output with echoed_word set to exactly the text the tool returned."
        )

    def _instructions(_s: EchoInput) -> str:
        return (
            "# Role — MCP echo probe\n\n"
            "You are a probe used by Agent Foundry's MCP integration test. "
            "When asked, call the specified MCP tool and return the result as structured output.\n"
        )

    agent = AgentAction[EchoInput, EchoOutput](
        name="echo-probe",
        model="claude-haiku-4-5-20251001",
        prompt_builder=_prompt,
        instructions_provider=_instructions,
        executor=run_agent_in_container,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        mcp_servers={"echo": StdioMcpServer(command="bash", args=["-c", _ECHO_SERVER_SCRIPT])},
        skip_permissions=True,
    )

    plan = PrimitivePlan(root=agent)
    runs_dir = Path(__file__).parent / "runs"
    runs_dir.mkdir(exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    result = await run_primitive_plan(
        plan,
        initial_state=EchoInput(word=ECHO_WORD),
        artifacts_dir=runs_dir,
        run_id=run_id,
        workspace_volume=workspace_volume,
        base_image_tag=base_image,
        responder_provider=static_provider(_FailResponder()),
    )

    assert isinstance(result, EchoOutput)
    assert result.echoed_word == ECHO_WORD
