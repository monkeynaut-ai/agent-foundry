#!/usr/bin/env python3
"""Claude Code adapter for the Agent Container Protocol.

Launches Claude Code in headless mode with structured JSON output:
    claude -p "prompt" --output-format stream-json --verbose

Turn results are delivered via Claude Code's ``--json-schema`` /
``StructuredOutput`` tool-call, parsed into ``StructuredOutputMessage``
protocol messages. Free-text output is relayed as ``OutputMessage``.
"""

import contextlib
import json
import logging
import subprocess
import sys
import threading
import time
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as ws_connect

from agent_foundry.agents.adapter import AdapterBase, TurnResult
from agent_foundry.agents.claude_code_events import (
    NON_RECOVERABLE_STOP_REASONS,
    STRUCTURED_OUTPUT_TOOL_NAME,
    AssistantEvent,
    ErrorEvent,
    ResultEvent,
    SystemInitEvent,
    TextBlock,
    ToolUseBlock,
    parse_stream_event,
)

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
    prompt: str,
    session_id: str | None = None,
    skip_permissions: bool = False,
    json_schema: dict[str, Any] | None = None,
) -> list[str]:
    """Build the claude CLI command for headless mode."""
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if session_id:
        cmd.extend(["--resume", session_id])
    if skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    if json_schema is not None:
        cmd.extend(["--json-schema", json.dumps(json_schema)])
    return cmd


class ClaudeCodeAdapter(AdapterBase):
    """Claude Code adapter — relays free-text output and structured results.

    Args:
        skip_permissions: Pass --dangerously-skip-permissions to claude CLI.
        turn_timeout: Timeout per turn in seconds.
        connect_timeout: Timeout for WebSocket connection in seconds.
    """

    def __init__(
        self,
        skip_permissions: bool = False,
        turn_timeout: float = 600.0,
        connect_timeout: float = 30.0,
    ):
        self._skip_permissions = skip_permissions
        self._turn_timeout = turn_timeout
        self._connect_timeout = connect_timeout
        self._in_structured_output_retry = False

    def _map_event_to_protocol(
        self,
        event: AssistantEvent | ResultEvent | ErrorEvent,
        session_id: str,
        stderr_tail: str = "",
    ) -> tuple[list[dict[str, Any]], bool]:
        """Map a typed Claude Code event to protocol messages.

        Accepts typed event models from ``claude_code_events``. The caller
        (``run_turn``) parses raw JSON into typed events at the boundary;
        this method never sees raw dicts.

        Returns (messages, task_complete).
        """
        ts = time.time()
        messages: list[dict[str, Any]] = []
        task_complete = False

        if isinstance(event, AssistantEvent):
            for block in event.message.content:
                if isinstance(block, TextBlock):
                    if not block.text.strip():
                        continue
                    messages.append(
                        {
                            "type": "output",
                            "session_id": session_id,
                            "text": block.text.strip(),
                            "stream": "stdout",
                            "timestamp": ts,
                        }
                    )
                elif isinstance(block, ToolUseBlock):
                    if block.name == STRUCTURED_OUTPUT_TOOL_NAME:
                        messages.append(
                            {
                                "type": "structured_output",
                                "session_id": session_id,
                                "payload": block.input,
                                "timestamp": ts,
                            }
                        )
                        task_complete = True
                        continue
                    summary = f"[tool_use: {block.name}]"
                    for key in ("command", "file_path", "query"):
                        if key in block.input:
                            summary = f"[tool_use: {block.name}] {block.input[key]}"
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

        elif isinstance(event, ResultEvent):
            exit_code = 1 if event.is_error else 0
            detail = event.stop_reason
            if event.is_error and stderr_tail:
                detail = f"{detail}\n{stderr_tail}".strip() if detail else stderr_tail
            messages.append(
                {
                    "type": "status",
                    "session_id": session_id,
                    "status": "turn_complete",
                    "exit_code": exit_code,
                    "detail": detail,
                    "timestamp": ts,
                }
            )

        elif isinstance(event, ErrorEvent):
            messages.append(
                {
                    "type": "output",
                    "session_id": session_id,
                    "text": f"[error] {event.error.message}",
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
        json_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> TurnResult:
        """Run a single Claude Code headless turn."""
        timeout = timeout or self._turn_timeout
        cmd = _build_claude_cmd(
            prompt,
            claude_session_id,
            skip_permissions=self._skip_permissions,
            json_schema=json_schema,
        )
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
        saw_terminal_status = False
        captured_structured_output: dict[str, Any] | None = None
        captured_stop_reason: str = ""
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
                saw_terminal_status = True
                break

            line = line.strip()
            if not line:
                continue

            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Non-JSON line from claude: %s", line[:200])
                continue

            # Parse at the boundary — typed from here on.
            event = parse_stream_event(raw)
            if event is None:
                continue  # Unknown event type (rate_limit, user synthetic, etc.)

            if isinstance(event, SystemInitEvent):
                captured_session_id = event.session_id
                continue  # No protocol messages for init events

            # For result events, pass stderr tail so it can be folded into the detail
            stderr_tail = ""
            if isinstance(event, ResultEvent):
                stderr_thread.join(timeout=2)
                stderr_tail = "\n".join(stderr_lines)

            protocol_msgs, is_complete = self._map_event_to_protocol(
                event, protocol_session_id, stderr_tail=stderr_tail
            )
            if is_complete:
                saw_task_complete = True
            for msg in protocol_msgs:
                if msg.get("type") == "structured_output":
                    captured_structured_output = msg["payload"]
                if msg.get("type") == "status" and msg.get("status") in (
                    "turn_complete",
                    "error",
                ):
                    saw_terminal_status = True
                _send_msg(msg)

            if isinstance(event, ResultEvent):
                exit_code = 1 if event.is_error else 0
                captured_stop_reason = event.stop_reason

        actual_exit_code = proc.wait()
        stderr_thread.join(timeout=2)

        if stderr_lines:
            logger.info("Claude stderr: %s", "\n".join(stderr_lines))

        # Path 2: process crashed before any result event
        if actual_exit_code != 0 and not saw_terminal_status:
            exit_code = actual_exit_code
            stderr_tail_str = "\n".join(stderr_lines)
            _send_msg(
                {
                    "type": "status",
                    "session_id": protocol_session_id,
                    "status": "error",
                    "exit_code": actual_exit_code,
                    "detail": stderr_tail_str,
                    "timestamp": time.time(),
                }
            )
            saw_terminal_status = True

        # Retry once if json_schema was set but no StructuredOutput was captured,
        # UNLESS the stop reason indicates a non-recoverable condition.
        # See: https://platform.claude.com/docs/en/build-with-claude/structured-outputs#invalid-outputs
        if (
            json_schema is not None
            and captured_structured_output is None
            and not self._in_structured_output_retry
            and captured_stop_reason not in NON_RECOVERABLE_STOP_REASONS
        ):
            logger.info("No StructuredOutput captured; retrying with --resume")
            self._in_structured_output_retry = True
            try:
                return self.run_turn(
                    prompt=(
                        "You must call the StructuredOutput tool with your response. "
                        "Do not respond with plain text."
                    ),
                    ws=ws,
                    protocol_session_id=protocol_session_id,
                    claude_session_id=captured_session_id,
                    timeout=timeout,
                    json_schema=json_schema,
                )
            finally:
                self._in_structured_output_retry = False

        return TurnResult(
            agent_session_id=captured_session_id,
            exit_code=exit_code,
            task_complete=saw_task_complete,
            structured_output=captured_structured_output,
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
                logger.info("Sending status: completed (source: structured_output)")
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

    parser = argparse.ArgumentParser(description="Claude Code adapter")
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
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_adapter_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    adapter = ClaudeCodeAdapter(
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
