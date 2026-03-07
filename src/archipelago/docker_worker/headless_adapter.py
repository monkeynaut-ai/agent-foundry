#!/usr/bin/env python3
"""Headless adapter: launches Claude Code in headless mode with structured JSON output.

Instead of spawning a PTY and scraping TUI output, this adapter uses:
    claude -p "prompt" --output-format stream-json --verbose

Each stdout line is a complete JSON object. Multi-turn conversations use --resume.

Usage:
    # As a library
    from headless_adapter import run_headless_adapter

    # As a CLI (connects to a WS server as protocol client)
    python headless_adapter.py --protocol ws://localhost:8765 "implement feature X"
"""

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

from archipelago.docker_worker.protocol import INTERRUPT_PATTERN as _INTERRUPT_PATTERN

logger = logging.getLogger(__name__)

# Marker that Claude outputs (via CLAUDE.md instructions) when it considers the task done.
# The adapter detects this and sends status:completed. The container stays alive
# so the gate node can resume the session if it rejects the work.
TASK_COMPLETE_MARKER = "ARCHIPELAGO_TASK_COMPLETE"
_TASK_COMPLETE_PATTERN = re.compile(rf"^{re.escape(TASK_COMPLETE_MARKER)}$", re.MULTILINE)


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
                raise ConnectionError(
                    f"Could not connect to {ws_url} within {timeout}s"
                ) from e
            delay = intervals[min(attempt, len(intervals) - 1)]
            remaining = deadline - time.monotonic()
            time.sleep(min(delay, max(0, remaining)))
            attempt += 1


def _build_claude_cmd(prompt: str, session_id: str | None = None) -> list[str]:
    """Build the claude CLI command for headless mode."""
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if session_id:
        cmd.extend(["--resume", session_id])
    return cmd


def _map_event_to_protocol(
    event: dict[str, Any], session_id: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Map a Claude Code stream-json event to zero or more protocol messages.

    Returns (messages, task_complete) where task_complete is True if the
    ARCHIPELAGO_TASK_COMPLETE marker was found in assistant output.
    """
    ts = time.time()
    event_type = event.get("type", "")
    messages: list[dict[str, Any]] = []
    task_complete = False

    if event_type == "system" and event.get("subtype") == "init":
        # Capture the Claude Code session_id for resume capability
        # Don't emit a protocol message — the adapter already sent "started"
        pass

    elif event_type == "assistant":
        # Extract text content from the assistant message
        msg = event.get("message", {})
        for block in msg.get("content", []):
            if block.get("type") == "text":
                text = block["text"]
                if not text.strip():
                    continue
                # Scan line by line for markers; collect remaining lines as output
                output_lines: list[str] = []
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped == TASK_COMPLETE_MARKER:
                        task_complete = True
                        continue
                    interrupt_match = _INTERRUPT_PATTERN.match(stripped)
                    if interrupt_match:
                        kind = interrupt_match.group(1)
                        try:
                            payload = json.loads(interrupt_match.group(2))
                        except json.JSONDecodeError:
                            output_lines.append(line)
                            continue
                        interrupt_type = "clarification" if kind == "CLARIFICATION" else "permission"
                        messages.append({
                            "type": "interrupt",
                            "session_id": session_id,
                            "interrupt_type": interrupt_type,
                            "payload": payload,
                            "raw_line": stripped,
                            "timestamp": ts,
                        })
                        continue
                    output_lines.append(line)
                remaining = "\n".join(output_lines).strip()
                if remaining:
                    messages.append({
                        "type": "output",
                        "session_id": session_id,
                        "text": remaining,
                        "stream": "stdout",
                        "timestamp": ts,
                    })
            elif block.get("type") == "tool_use":
                # Report tool usage as output
                tool_name = block.get("name", "unknown")
                tool_input = block.get("input", {})
                summary = f"[tool_use: {tool_name}]"
                # Include a brief summary of the input for visibility
                if isinstance(tool_input, dict):
                    if "command" in tool_input:
                        summary = f"[tool_use: {tool_name}] {tool_input['command']}"
                    elif "file_path" in tool_input:
                        summary = f"[tool_use: {tool_name}] {tool_input['file_path']}"
                    elif "query" in tool_input:
                        summary = f"[tool_use: {tool_name}] {tool_input['query']}"
                messages.append({
                    "type": "output",
                    "session_id": session_id,
                    "text": summary,
                    "stream": "stdout",
                    "timestamp": ts,
                })

    elif event_type == "tool_result":
        # Tool results — optionally emit as output for visibility
        pass

    elif event_type == "result":
        # Turn finished — send turn_complete (not exited, adapter stays alive for more turns)
        is_error = event.get("is_error", False)
        exit_code = 1 if is_error else 0
        messages.append({
            "type": "status",
            "session_id": session_id,
            "status": "turn_complete",
            "exit_code": exit_code,
            "detail": event.get("stop_reason", ""),
            "timestamp": ts,
        })

    elif event_type == "rate_limit_event":
        # Could be useful for monitoring but not critical for protocol
        pass

    elif event_type == "error":
        messages.append({
            "type": "output",
            "session_id": session_id,
            "text": f"[error] {event.get('error', {}).get('message', 'unknown error')}",
            "stream": "stderr",
            "timestamp": ts,
        })

    return messages, task_complete


def run_headless_turn(
    prompt: str,
    ws,
    protocol_session_id: str,
    claude_session_id: str | None = None,
    timeout: float = 600.0,
) -> tuple[str | None, int, bool]:
    """Run a single headless turn: send prompt to Claude Code, stream events to WS.

    Returns (claude_session_id, exit_code, task_complete).
    task_complete is True if ARCHIPELAGO_TASK_COMPLETE was found in output.
    The claude_session_id can be used for --resume on the next turn.
    """
    cmd = _build_claude_cmd(prompt, claude_session_id)
    logger.info("Running: %s", " ".join(cmd))

    captured_session_id = claude_session_id

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,  # line-buffered
    )

    exit_code = 1
    saw_task_complete = False
    deadline = time.monotonic() + timeout

    def _send_msg(msg: dict) -> None:
        try:
            ws.send(json.dumps(msg))
        except (ConnectionClosed, OSError):
            pass

    # Read stderr in a background thread
    stderr_lines: list[str] = []
    def _read_stderr():
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line.rstrip())

    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stderr_thread.start()

    # Read stdout line by line — each line is a JSON event
    assert proc.stdout is not None
    for line in proc.stdout:
        if time.monotonic() > deadline:
            proc.terminate()
            _send_msg({
                "type": "status",
                "session_id": protocol_session_id,
                "status": "error",
                "detail": "timeout",
                "timestamp": time.time(),
            })
            break

        line = line.strip()
        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Non-JSON line from claude: %s", line[:200])
            continue

        # Capture Claude's session_id for resume
        if event.get("type") == "system" and event.get("subtype") == "init":
            captured_session_id = event.get("session_id", captured_session_id)

        # Map to protocol messages and send
        protocol_msgs, is_complete = _map_event_to_protocol(event, protocol_session_id)
        if is_complete:
            saw_task_complete = True
        for msg in protocol_msgs:
            _send_msg(msg)

        # Check if this was the final result
        if event.get("type") == "result":
            exit_code = 1 if event.get("is_error", False) else 0

    proc.wait()
    stderr_thread.join(timeout=2)

    if stderr_lines:
        logger.info("Claude stderr: %s", "\n".join(stderr_lines))

    return captured_session_id, exit_code, saw_task_complete


def run_headless_adapter(
    initial_prompt: str | None,
    ws_url: str,
    protocol_session_id: str = "default",
    connect_timeout: float = 30.0,
    turn_timeout: float = 600.0,
) -> int:
    """Run a headless adapter session.

    Connects to ws_url and listens for input/control messages from the orchestrator.
    If initial_prompt is given, runs the first Claude turn immediately on connect.
    If None, waits for the first input message before running any turn.
    """
    try:
        ws = _connect_with_backoff(ws_url, timeout=connect_timeout)
    except ConnectionError as e:
        logger.error("Failed to connect: %s", e)
        return 1

    ts = time.time

    def _send_msg(msg: dict) -> None:
        try:
            ws.send(json.dumps(msg))
        except (ConnectionClosed, OSError):
            pass

    # Send started status
    _send_msg({
        "type": "status",
        "session_id": protocol_session_id,
        "status": "started",
        "timestamp": ts(),
    })

    claude_session_id: str | None = None
    exit_code = 0
    completed = False

    # Run initial turn if prompt provided; otherwise wait for first input message
    if initial_prompt is not None:
        _send_msg({
            "type": "status",
            "session_id": protocol_session_id,
            "status": "running",
            "timestamp": ts(),
        })

        claude_session_id, exit_code, task_complete = run_headless_turn(
            initial_prompt, ws, protocol_session_id, timeout=turn_timeout,
        )

        if task_complete:
            completed = True
            _send_msg({
                "type": "status",
                "session_id": protocol_session_id,
                "status": "completed",
                "exit_code": exit_code,
                "timestamp": ts(),
            })

    # Listen for follow-up input/control messages
    # After "completed", adapter stays alive — gate may resume or terminate
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

                _send_msg({
                    "type": "status",
                    "session_id": protocol_session_id,
                    "status": "running",
                    "timestamp": ts(),
                })

                claude_session_id, exit_code, task_complete = run_headless_turn(
                    text, ws, protocol_session_id,
                    claude_session_id=claude_session_id,
                    timeout=turn_timeout,
                )

                if task_complete:
                    completed = True
                    _send_msg({
                        "type": "status",
                        "session_id": protocol_session_id,
                        "status": "completed",
                        "exit_code": exit_code,
                        "timestamp": ts(),
                    })

            elif msg_type == "control":
                cmd = msg.get("command")
                if cmd == "complete":
                    # Outside-in: node/human/component says we're done
                    completed = True
                    break
                elif cmd in ("terminate", "kill"):
                    break

    except ConnectionClosed:
        pass

    # Send final status
    final_status = "completed" if completed else "exited"
    _send_msg({
        "type": "status",
        "session_id": protocol_session_id,
        "status": final_status,
        "exit_code": exit_code,
        "timestamp": ts(),
    })

    try:
        ws.close()
    except Exception:
        pass

    return exit_code


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Headless Claude Code adapter")
    parser.add_argument(
        "prompt", nargs="?", default=None,
        help="initial prompt to send to Claude Code (if omitted, waits for first input message over WS)",
    )
    parser.add_argument(
        "--protocol",
        metavar="WS_URL",
        default="ws://localhost:8765",
        help="WebSocket URL to connect to (default: ws://localhost:8765)",
    )
    parser.add_argument(
        "--session-id",
        default="default",
        help="protocol session ID (default: 'default')",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="timeout per turn in seconds (default: 600)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    sys.exit(run_headless_adapter(
        initial_prompt=args.prompt,
        ws_url=args.protocol,
        protocol_session_id=args.session_id,
        turn_timeout=args.timeout,
    ))
