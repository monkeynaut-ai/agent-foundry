#!/usr/bin/env python3
"""Claude Code adapter for the Agent Container Protocol.

Launches Claude Code in headless mode with structured JSON output:
    claude -p "prompt" --output-format stream-json --verbose

Marker detection is configurable via MarkerMapping — no product-specific
markers are hardcoded. Products pass their marker definitions through the
role stack.
"""

import contextlib
import json
import logging
import re
import subprocess
import sys
import threading
import time
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as ws_connect

from agent_foundry.acp.adapter import AdapterBase, TurnResult
from agent_foundry.acp.protocol import MarkerMapping

logger = logging.getLogger(__name__)


def _connect_with_backoff(ws_url: str, timeout: float = 30.0):
    """Connect to a WebSocket with exponential backoff."""
    intervals = [0.5, 1.0, 2.0, 4.0]
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        try:
            return ws_connect(ws_url)
        except (ConnectionRefusedError, OSError) as e:
            if time.monotonic() >= deadline:
                raise ConnectionError(f"Could not connect to {ws_url} within {timeout}s") from e
            delay = intervals[min(attempt, len(intervals) - 1)]
            remaining = deadline - time.monotonic()
            time.sleep(min(delay, max(0, remaining)))
            attempt += 1


def _build_claude_cmd(
    prompt: str, session_id: str | None = None, skip_permissions: bool = False
) -> list[str]:
    """Build the claude CLI command for headless mode."""
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if session_id:
        cmd.extend(["--resume", session_id])
    if skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    return cmd


class ClaudeCodeAdapter(AdapterBase):
    """Claude Code adapter with configurable marker-to-event mapping.

    Args:
        marker_mappings: List of MarkerMapping defining how stdout markers
            translate to ACP events.
        skip_permissions: Pass --dangerously-skip-permissions to claude CLI.
        turn_timeout: Timeout per turn in seconds.
        connect_timeout: Timeout for WebSocket connection in seconds.
    """

    def __init__(
        self,
        marker_mappings: list[MarkerMapping] | None = None,
        skip_permissions: bool = False,
        turn_timeout: float = 600.0,
        connect_timeout: float = 30.0,
    ):
        self._marker_mappings = marker_mappings or []
        self._compiled_markers = [
            (re.compile(m.pattern), m.event_type, m.payload_group) for m in self._marker_mappings
        ]
        self._skip_permissions = skip_permissions
        self._turn_timeout = turn_timeout
        self._connect_timeout = connect_timeout

    def _match_marker(self, line: str) -> tuple[str, dict[str, Any]] | None:
        """Check if a line matches any configured marker.

        Returns (event_type, payload) or None.
        """
        for compiled, event_type, payload_group in self._compiled_markers:
            match = compiled.match(line)
            if match:
                payload: dict[str, Any] = {}
                if payload_group is not None:
                    try:
                        payload = json.loads(match.group(payload_group))
                    except (json.JSONDecodeError, IndexError):
                        continue  # Malformed payload — skip this marker
                return event_type, payload
        return None

    def _map_event_to_protocol(
        self,
        event: dict[str, Any],
        session_id: str,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Map a Claude Code stream-json event to protocol messages.

        Returns (messages, task_complete).
        """
        ts = time.time()
        event_type = event.get("type", "")
        messages: list[dict[str, Any]] = []
        task_complete = False

        if event_type == "assistant":
            msg = event.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") == "text":
                    text = block["text"]
                    if not text.strip():
                        continue
                    output_lines: list[str] = []
                    for line in text.splitlines():
                        stripped = line.strip()
                        marker_result = self._match_marker(stripped)
                        if marker_result:
                            evt_type, payload = marker_result
                            if evt_type == "task_complete":
                                task_complete = True
                                logger.info("Task complete marker detected")
                                continue
                            messages.append(
                                {
                                    "type": "agent_event",
                                    "session_id": session_id,
                                    "event_type": evt_type,
                                    "payload": payload,
                                    "raw_line": stripped,
                                    "timestamp": ts,
                                }
                            )
                            continue
                        output_lines.append(line)
                    remaining = "\n".join(output_lines).strip()
                    if remaining:
                        messages.append(
                            {
                                "type": "output",
                                "session_id": session_id,
                                "text": remaining,
                                "stream": "stdout",
                                "timestamp": ts,
                            }
                        )
                elif block.get("type") == "tool_use":
                    tool_name = block.get("name", "unknown")
                    tool_input = block.get("input", {})
                    summary = f"[tool_use: {tool_name}]"
                    if isinstance(tool_input, dict):
                        for key in ("command", "file_path", "query"):
                            if key in tool_input:
                                summary = f"[tool_use: {tool_name}] {tool_input[key]}"
                                break
                    messages.append(
                        {
                            "type": "output",
                            "session_id": session_id,
                            "text": summary,
                            "stream": "stdout",
                            "timestamp": ts,
                        }
                    )

        elif event_type == "result":
            is_error = event.get("is_error", False)
            exit_code = 1 if is_error else 0
            messages.append(
                {
                    "type": "status",
                    "session_id": session_id,
                    "status": "turn_complete",
                    "exit_code": exit_code,
                    "detail": event.get("stop_reason", ""),
                    "timestamp": ts,
                }
            )

        elif event_type == "error":
            messages.append(
                {
                    "type": "output",
                    "session_id": session_id,
                    "text": f"[error] {event.get('error', {}).get('message', 'unknown error')}",
                    "stream": "stderr",
                    "timestamp": ts,
                }
            )

        return messages, task_complete

    def run_turn(
        self,
        prompt: str,
        ws: Any,
        protocol_session_id: str,
        claude_session_id: str | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> TurnResult:
        """Run a single Claude Code headless turn."""
        timeout = timeout or self._turn_timeout
        cmd = _build_claude_cmd(prompt, claude_session_id, skip_permissions=self._skip_permissions)
        logger.info("Running: %s", " ".join(cmd))

        captured_session_id = claude_session_id

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        exit_code = 1
        saw_task_complete = False
        deadline = time.monotonic() + timeout

        def _send_msg(msg: dict) -> None:
            with contextlib.suppress(ConnectionClosed, OSError):
                ws.send(json.dumps(msg))

        stderr_lines: list[str] = []

        def _read_stderr():
            assert proc.stderr is not None
            for line in proc.stderr:
                stderr_lines.append(line.rstrip())

        stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
        stderr_thread.start()

        assert proc.stdout is not None
        for line in proc.stdout:
            if time.monotonic() > deadline:
                proc.terminate()
                _send_msg(
                    {
                        "type": "status",
                        "session_id": protocol_session_id,
                        "status": "error",
                        "detail": "timeout",
                        "timestamp": time.time(),
                    }
                )
                break

            line = line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Non-JSON line from claude: %s", line[:200])
                continue

            if event.get("type") == "system" and event.get("subtype") == "init":
                captured_session_id = event.get("session_id", captured_session_id)

            protocol_msgs, is_complete = self._map_event_to_protocol(event, protocol_session_id)
            if is_complete:
                saw_task_complete = True
            for msg in protocol_msgs:
                _send_msg(msg)

            if event.get("type") == "result":
                exit_code = 1 if event.get("is_error", False) else 0

        proc.wait()
        stderr_thread.join(timeout=2)

        if stderr_lines:
            logger.info("Claude stderr: %s", "\n".join(stderr_lines))

        return TurnResult(
            agent_session_id=captured_session_id,
            exit_code=exit_code,
            task_complete=saw_task_complete,
        )

    def run(
        self,
        initial_prompt: str | None,
        ws_url: str,
        protocol_session_id: str = "default",
        **kwargs: Any,
    ) -> int:
        """Run the full adapter loop."""
        try:
            ws = _connect_with_backoff(ws_url, timeout=self._connect_timeout)
        except ConnectionError as e:
            logger.error("Failed to connect: %s", e)
            return 1

        ts = time.time

        def _send_msg(msg: dict) -> None:
            with contextlib.suppress(ConnectionClosed, OSError):
                ws.send(json.dumps(msg))

        _send_msg(
            {
                "type": "status",
                "session_id": protocol_session_id,
                "status": "started",
                "timestamp": ts(),
            }
        )

        claude_session_id: str | None = None
        exit_code = 0
        completed = False

        if initial_prompt is not None:
            _send_msg(
                {
                    "type": "status",
                    "session_id": protocol_session_id,
                    "status": "running",
                    "timestamp": ts(),
                }
            )

            result = self.run_turn(
                initial_prompt,
                ws,
                protocol_session_id,
            )
            claude_session_id = result.agent_session_id
            exit_code = result.exit_code

            if result.task_complete:
                completed = True
                logger.info("Sending status: completed (source: task_complete_marker)")
                _send_msg(
                    {
                        "type": "status",
                        "session_id": protocol_session_id,
                        "status": "completed",
                        "exit_code": exit_code,
                        "timestamp": ts(),
                    }
                )

        try:
            while True:
                try:
                    raw = ws.recv(timeout=1.0)
                except TimeoutError:
                    continue
                except ConnectionClosed:
                    break

                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue

                msg_type = msg.get("type")
                if msg_type == "input":
                    text = msg.get("text", "").strip()
                    if not text:
                        continue

                    _send_msg(
                        {
                            "type": "status",
                            "session_id": protocol_session_id,
                            "status": "running",
                            "timestamp": ts(),
                        }
                    )

                    result = self.run_turn(
                        text,
                        ws,
                        protocol_session_id,
                        claude_session_id=claude_session_id,
                    )
                    claude_session_id = result.agent_session_id
                    exit_code = result.exit_code

                    if result.task_complete:
                        completed = True
                        _send_msg(
                            {
                                "type": "status",
                                "session_id": protocol_session_id,
                                "status": "completed",
                                "exit_code": exit_code,
                                "timestamp": ts(),
                            }
                        )

                elif msg_type == "control":
                    cmd = msg.get("command")
                    if cmd == "complete":
                        completed = True
                        break
                    elif cmd in ("terminate", "kill"):
                        break

        except ConnectionClosed:
            pass

        final_status = "completed" if completed else "exited"
        _send_msg(
            {
                "type": "status",
                "session_id": protocol_session_id,
                "status": final_status,
                "exit_code": exit_code,
                "timestamp": ts(),
            }
        )

        with contextlib.suppress(Exception):
            ws.close()

        return exit_code


def _parse_adapter_args(argv=None):
    """Parse adapter CLI arguments. Exposed for testing."""
    import argparse

    parser = argparse.ArgumentParser(description="Claude Code ACP adapter")
    parser.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="initial prompt (if omitted, waits for first input message over WS)",
    )
    parser.add_argument(
        "--protocol",
        metavar="WS_URL",
        default="ws://localhost:8765",
        help="WebSocket URL to connect to",
    )
    parser.add_argument(
        "--session-id",
        default="default",
        help="protocol session ID",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="timeout per turn in seconds",
    )
    parser.add_argument(
        "--dangerously-skip-permissions",
        action="store_true",
        default=False,
        help="pass --dangerously-skip-permissions to claude CLI",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="enable debug logging",
    )
    parser.add_argument(
        "--marker-config",
        default=None,
        help="path to JSON file defining marker mappings",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_adapter_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Load marker mappings from config file if provided
    mappings: list[MarkerMapping] = []
    if args.marker_config:
        import pathlib

        raw = json.loads(pathlib.Path(args.marker_config).read_text())
        mappings = [MarkerMapping(**m) for m in raw]

    adapter = ClaudeCodeAdapter(
        marker_mappings=mappings,
        skip_permissions=args.dangerously_skip_permissions,
        turn_timeout=args.timeout,
    )

    sys.exit(
        adapter.run(
            initial_prompt=args.prompt,
            ws_url=args.protocol,
            protocol_session_id=args.session_id,
        )
    )
