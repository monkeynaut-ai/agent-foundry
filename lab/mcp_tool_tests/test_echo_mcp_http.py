"""Lab: MCP tool call end-to-end test via HTTP transport.

Same echo scenario as test_echo_mcp.py but using StreamableHttpMcpServer.
The MCP server runs as an HTTP service on the host, reachable from the
agent container via host.docker.internal.

Run:
    ./lab/mcp_tool_tests/run.sh
"""

from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from collections.abc import Generator
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn

import pytest
from dotenv import load_dotenv
from pydantic import BaseModel

from agent_foundry.orchestration.container_executor import run_agent_in_container
from agent_foundry.orchestration.runner import run_primitive_plan
from agent_foundry.primitives.mcp import StreamableHttpMcpServer
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

ECHO_WORD = "mangia bene"


class EchoInput(BaseModel):
    word: str


class EchoOutput(BaseModel):
    echoed_word: str


class _FailResponder(Responder):
    async def respond(
        self, request: ResponderRequest, context: ResponderContext
    ) -> ResponderResponse:
        raise AssertionError(f"responder unexpectedly called: {request!r}")


class _McpEchoHandler(BaseHTTPRequestHandler):
    """Minimal MCP Streamable HTTP server implementing the echo tool."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            msg = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400)
            return

        response = self._dispatch(msg)
        if response is None:
            # Notification — acknowledge with no body
            self.send_response(202)
            self.end_headers()
            return

        payload = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        # Claude Code may probe for SSE; we don't support server-push.
        self.send_response(405)
        self.end_headers()

    def _dispatch(self, msg: dict) -> dict | None:
        method = msg.get("method", "")
        id_ = msg.get("id")

        if id_ is None:
            return None  # notification — no response

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": id_,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "echo-http", "version": "0.1.0"},
                },
            }
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": id_,
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo the message back unchanged.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "message": {
                                        "type": "string",
                                        "description": "Text to echo.",
                                    }
                                },
                                "required": ["message"],
                            },
                        }
                    ]
                },
            }
        if method == "tools/call":
            text = msg.get("params", {}).get("arguments", {}).get("message", "")
            return {
                "jsonrpc": "2.0",
                "id": id_,
                "result": {"content": [{"type": "text", "text": text}]},
            }
        return {
            "jsonrpc": "2.0",
            "id": id_,
            "error": {"code": -32601, "message": "Method not found"},
        }

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write(f"[mcp-http] {format % args}\n")
        sys.stderr.flush()


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


@pytest.fixture
def http_echo_server() -> Generator[str]:
    """Start an HTTP MCP echo server on a free port; yield its URL.

    Binds to 0.0.0.0 so the container can reach it via host.docker.internal.
    """
    server = _ThreadingHTTPServer(("0.0.0.0", 0), _McpEchoHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://host.docker.internal:{port}/mcp"
    server.shutdown()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_calls_http_mcp_tool(http_echo_server: str) -> None:
    """Agent uses an HTTP MCP server running on the host to call the echo
    tool and returns the result in structured output."""

    oauth_token = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
    assert oauth_token

    try:
        import docker

        client = docker.from_env()
        client.ping()
    except Exception as e:
        pytest.skip(f"docker daemon unavailable: {e}")

    base_image = os.environ.get("AGENT_BASE_IMAGE", "agent-worker:latest")
    workspace_volume = f"mcp-echo-http-{uuid.uuid4().hex[:8]}"

    def _prompt(s: EchoInput) -> str:
        return (
            f"You have access to an MCP server named 'echo' with one tool also called 'echo'. "
            f"Call the echo tool with message='{s.word}'. "
            f"Return structured output with echoed_word set to exactly the text the tool returned."
        )

    def _instructions(_s: EchoInput) -> str:
        return (
            "# Role — MCP echo probe (HTTP)\n\n"
            "You are a probe used by Agent Foundry's MCP HTTP transport integration test. "
            "When asked, call the specified MCP tool and return the result as structured output.\n"
        )

    agent = AgentAction[EchoInput, EchoOutput](
        name="echo-probe-http",
        model="claude-haiku-4-5-20251001",
        prompt_builder=_prompt,
        instructions_provider=_instructions,
        executor=run_agent_in_container,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        mcp_servers={"echo": StreamableHttpMcpServer(url=http_echo_server)},
        skip_permissions=True,
    )

    runs_dir = Path(__file__).parent / "runs"
    runs_dir.mkdir(exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-http")

    result = await run_primitive_plan(
        PrimitivePlan(root=agent),
        initial_state=EchoInput(word=ECHO_WORD),
        artifacts_dir=runs_dir,
        run_id=run_id,
        workspace_volume=workspace_volume,
        base_image_tag=base_image,
        responder_provider=static_provider(_FailResponder()),
    )

    assert isinstance(result, EchoOutput)
    assert result.echoed_word == ECHO_WORD
