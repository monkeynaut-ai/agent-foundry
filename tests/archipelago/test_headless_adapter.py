"""Headless adapter tests.

Uses mock subprocesses emitting canned stream-json events and a real WS server
to verify protocol message translation and incoming message handling.
"""

import io
import json
import socket
import threading
import time
from unittest.mock import MagicMock, patch

from websockets.sync.server import serve

from archipelago.docker_worker.headless_adapter import (
    _map_event_to_protocol,
    run_headless_adapter,
    run_headless_turn,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _make_mock_proc(stdout_lines: list[str], stderr_lines: list[str] | None = None):
    """Mock subprocess.Popen with canned stdout stream-json lines."""
    proc = MagicMock()
    proc.stdout = io.StringIO("\n".join(stdout_lines) + "\n")
    proc.stderr = io.StringIO("\n".join(stderr_lines or []))
    proc.wait.return_value = None
    proc.terminate.return_value = None
    return proc


class _MockWS:
    """Minimal WS stub for run_headless_turn tests — captures sent messages."""

    def __init__(self):
        self.sent: list[dict] = []

    def send(self, msg: str) -> None:
        self.sent.append(json.loads(msg))


class _WSTestServer:
    """Real WS server for run_headless_adapter tests — collects messages, sends commands."""

    def __init__(self, port: int):
        self.port = port
        self.received: list[dict] = []
        self._ws = None
        self._connected = threading.Event()
        self._server = serve(self._handler, "localhost", port)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def _handler(self, ws):
        self._ws = ws
        self._connected.set()
        try:
            while True:
                try:
                    self.received.append(json.loads(ws.recv(timeout=0.2)))
                except TimeoutError:
                    continue
        except Exception:
            pass

    def wait_connected(self, timeout: float = 5.0) -> bool:
        return self._connected.wait(timeout=timeout)

    def send(self, msg: dict) -> None:
        if self._ws:
            self._ws.send(json.dumps(msg))

    def statuses(self) -> list[str]:
        return [m["status"] for m in self.received if m.get("type") == "status"]

    def shutdown(self):
        self._server.shutdown()


def _event(type_: str, **kwargs) -> str:
    return json.dumps({"type": type_, **kwargs})


def _assistant_text(text: str) -> str:
    return _event("assistant", message={"content": [{"type": "text", "text": text}]})


def _assistant_tool(name: str, input_: dict) -> str:
    return _event(
        "assistant", message={"content": [{"type": "tool_use", "name": name, "input": input_}]}
    )


def _result(is_error: bool = False, stop_reason: str = "end_turn") -> str:
    return _event("result", is_error=is_error, stop_reason=stop_reason)


def _fake_turn(prompt, ws, session_id, claude_session_id=None, timeout=600.0):
    return "fake-session-id", 0, False


# ── _map_event_to_protocol ────────────────────────────────────────────────────


class TestMapEventToProtocol:
    """Given stream-json events, _map_event_to_protocol emits correct protocol messages."""

    SESSION = "test-session"

    def test_given_system_init_when_mapped_then_no_messages_emitted(self):
        event = {"type": "system", "subtype": "init", "session_id": "abc"}
        msgs, complete = _map_event_to_protocol(event, self.SESSION)
        assert msgs == []
        assert complete is False

    def test_given_assistant_text_when_mapped_then_output_message_emitted(self):
        event = json.loads(_assistant_text("hello world"))
        msgs, complete = _map_event_to_protocol(event, self.SESSION)
        assert len(msgs) == 1
        assert msgs[0]["type"] == "output"
        assert msgs[0]["text"] == "hello world"
        assert msgs[0]["stream"] == "stdout"
        assert complete is False

    def test_given_assistant_tool_use_when_mapped_then_tool_summary_emitted(self):
        event = json.loads(_assistant_tool("Bash", {"command": "ls -la"}))
        msgs, _complete = _map_event_to_protocol(event, self.SESSION)
        assert len(msgs) == 1
        assert msgs[0]["type"] == "output"
        assert "Bash" in msgs[0]["text"]
        assert "ls -la" in msgs[0]["text"]

    def test_given_task_complete_marker_when_mapped_then_task_complete_true(self):
        event = json.loads(_assistant_text("ARCHIPELAGO_TASK_COMPLETE"))
        _msgs, complete = _map_event_to_protocol(event, self.SESSION)
        assert complete is True

    def test_given_task_complete_marker_when_mapped_then_marker_stripped_from_output(self):
        event = json.loads(_assistant_text("All done!\nARCHIPELAGO_TASK_COMPLETE"))
        msgs, complete = _map_event_to_protocol(event, self.SESSION)
        assert complete is True
        assert any("All done!" in m["text"] for m in msgs if m["type"] == "output")
        assert all("ARCHIPELAGO_TASK_COMPLETE" not in m.get("text", "") for m in msgs)

    def test_given_task_complete_marker_only_when_mapped_then_no_output_message(self):
        event = json.loads(_assistant_text("ARCHIPELAGO_TASK_COMPLETE"))
        msgs, complete = _map_event_to_protocol(event, self.SESSION)
        assert complete is True
        assert not any(m["type"] == "output" for m in msgs)

    def test_given_clarification_marker_when_mapped_then_interrupt_message_emitted(self):
        payload = {"question": "Which DB?", "options": ["pg", "sqlite"], "blocking": True}
        marker = f"ARCHIPELAGO_NEED_CLARIFICATION {json.dumps(payload)}"
        event = json.loads(_assistant_text(marker))
        msgs, complete = _map_event_to_protocol(event, self.SESSION)
        assert len(msgs) == 1
        assert msgs[0]["type"] == "interrupt"
        assert msgs[0]["interrupt_type"] == "clarification"
        assert msgs[0]["payload"]["question"] == "Which DB?"
        assert complete is False

    def test_given_permission_marker_when_mapped_then_interrupt_message_emitted(self):
        payload = {"action": "rm -rf /tmp/x", "risk_level": "low", "why_needed": "cleanup"}
        marker = f"ARCHIPELAGO_NEED_PERMISSION {json.dumps(payload)}"
        event = json.loads(_assistant_text(marker))
        msgs, _complete = _map_event_to_protocol(event, self.SESSION)
        assert len(msgs) == 1
        assert msgs[0]["type"] == "interrupt"
        assert msgs[0]["interrupt_type"] == "permission"
        assert msgs[0]["payload"]["action"] == "rm -rf /tmp/x"

    def test_given_malformed_interrupt_marker_when_mapped_then_plain_output_emitted(self):
        event = json.loads(_assistant_text("ARCHIPELAGO_NEED_CLARIFICATION {bad json}"))
        msgs, _complete = _map_event_to_protocol(event, self.SESSION)
        assert len(msgs) == 1
        assert msgs[0]["type"] == "output"
        assert "ARCHIPELAGO_NEED_CLARIFICATION" in msgs[0]["text"]

    def test_given_result_success_when_mapped_then_turn_complete_exit_code_zero(self):
        event = json.loads(_result(is_error=False, stop_reason="end_turn"))
        msgs, _complete = _map_event_to_protocol(event, self.SESSION)
        assert len(msgs) == 1
        assert msgs[0]["type"] == "status"
        assert msgs[0]["status"] == "turn_complete"
        assert msgs[0]["exit_code"] == 0

    def test_given_result_error_when_mapped_then_turn_complete_exit_code_one(self):
        event = json.loads(_result(is_error=True))
        msgs, _complete = _map_event_to_protocol(event, self.SESSION)
        assert msgs[0]["exit_code"] == 1

    def test_given_error_event_when_mapped_then_stderr_output_emitted(self):
        event = {"type": "error", "error": {"message": "rate limit hit"}}
        msgs, _complete = _map_event_to_protocol(event, self.SESSION)
        assert len(msgs) == 1
        assert msgs[0]["stream"] == "stderr"
        assert "rate limit hit" in msgs[0]["text"]


# ── run_headless_turn session ID capture ─────────────────────────────────────


class TestRunHeadlessTurnSessionId:
    """Session ID is captured from system.init and returned for --resume use."""

    def test_given_system_init_event_when_turn_runs_then_session_id_captured(self):
        lines = [
            _event("system", subtype="init", session_id="captured-id-123"),
            _result(),
        ]
        mock_proc = _make_mock_proc(lines)
        ws = _MockWS()

        with patch(
            "archipelago.docker_worker.headless_adapter.subprocess.Popen", return_value=mock_proc
        ):
            session_id, exit_code, task_complete = run_headless_turn(
                "do something", ws, "proto-session"
            )

        assert session_id == "captured-id-123"
        assert exit_code == 0
        assert task_complete is False

    def test_given_no_system_init_when_turn_runs_then_existing_session_id_preserved(self):
        lines = [_result()]
        mock_proc = _make_mock_proc(lines)
        ws = _MockWS()

        with patch(
            "archipelago.docker_worker.headless_adapter.subprocess.Popen", return_value=mock_proc
        ):
            session_id, _exit_code, _task_complete = run_headless_turn(
                "do something", ws, "proto-session", claude_session_id="existing-id"
            )

        assert session_id == "existing-id"


# ── run_headless_adapter — incoming message handling ─────────────────────────


class TestHeadlessAdapterIncomingMessages:
    """Adapter listen loop handles input and control messages correctly."""

    def test_given_input_message_when_received_then_triggers_new_turn(self):
        port = _free_port()
        server = _WSTestServer(port)
        turn_prompts: list[str] = []

        def capturing_turn(prompt, ws, session_id, claude_session_id=None, timeout=600.0):
            turn_prompts.append(prompt)
            return "sid", 0, False

        with patch(
            "archipelago.docker_worker.headless_adapter.run_headless_turn",
            side_effect=capturing_turn,
        ):
            t = threading.Thread(
                target=run_headless_adapter,
                kwargs={"initial_prompt": None, "ws_url": f"ws://localhost:{port}"},
                daemon=True,
            )
            t.start()
            server.wait_connected()
            time.sleep(0.2)

            server.send({"type": "input", "session_id": "s", "text": "implement X"})
            time.sleep(0.4)

            assert turn_prompts == ["implement X"]
            assert "running" in server.statuses()

        server.send({"type": "control", "command": "terminate"})
        t.join(timeout=5)
        server.shutdown()

    def test_given_blank_input_when_received_then_no_turn_spawned(self):
        port = _free_port()
        server = _WSTestServer(port)
        turn_calls: list = []

        def capturing_turn(prompt, ws, session_id, claude_session_id=None, timeout=600.0):
            turn_calls.append(prompt)
            return "sid", 0, False

        with patch(
            "archipelago.docker_worker.headless_adapter.run_headless_turn",
            side_effect=capturing_turn,
        ):
            t = threading.Thread(
                target=run_headless_adapter,
                kwargs={"initial_prompt": None, "ws_url": f"ws://localhost:{port}"},
                daemon=True,
            )
            t.start()
            server.wait_connected()
            time.sleep(0.2)

            server.send({"type": "input", "session_id": "s", "text": "   "})
            time.sleep(0.3)

            assert turn_calls == []

        server.send({"type": "control", "command": "terminate"})
        t.join(timeout=5)
        server.shutdown()

    def test_given_control_complete_when_received_then_sends_completed_and_exits(self):
        port = _free_port()
        server = _WSTestServer(port)

        with patch(
            "archipelago.docker_worker.headless_adapter.run_headless_turn", side_effect=_fake_turn
        ):
            t = threading.Thread(
                target=run_headless_adapter,
                kwargs={"initial_prompt": None, "ws_url": f"ws://localhost:{port}"},
                daemon=True,
            )
            t.start()
            server.wait_connected()
            time.sleep(0.2)

            server.send({"type": "control", "command": "complete"})
            t.join(timeout=5)

            assert not t.is_alive()
            assert "completed" in server.statuses()

        server.shutdown()

    def test_given_control_terminate_when_received_then_adapter_exits(self):
        port = _free_port()
        server = _WSTestServer(port)

        with patch(
            "archipelago.docker_worker.headless_adapter.run_headless_turn", side_effect=_fake_turn
        ):
            t = threading.Thread(
                target=run_headless_adapter,
                kwargs={"initial_prompt": None, "ws_url": f"ws://localhost:{port}"},
                daemon=True,
            )
            t.start()
            server.wait_connected()
            time.sleep(0.2)

            server.send({"type": "control", "command": "terminate"})
            t.join(timeout=5)

            assert not t.is_alive()

        server.shutdown()


# ── run_headless_adapter — initial prompt ────────────────────────────────────


class TestInitialPrompt:
    """Adapter handles optional initial_prompt correctly."""

    def test_given_no_prompt_when_adapter_starts_then_sends_started_without_running_turn(self):
        port = _free_port()
        server = _WSTestServer(port)

        with patch(
            "archipelago.docker_worker.headless_adapter.run_headless_turn", side_effect=_fake_turn
        ) as mock_turn:
            t = threading.Thread(
                target=run_headless_adapter,
                kwargs={"initial_prompt": None, "ws_url": f"ws://localhost:{port}"},
                daemon=True,
            )
            t.start()
            server.wait_connected()
            time.sleep(0.3)

            assert "started" in server.statuses()
            assert "running" not in server.statuses()
            mock_turn.assert_not_called()

        server.send({"type": "control", "command": "terminate"})
        t.join(timeout=5)
        server.shutdown()

    def test_given_initial_prompt_when_adapter_starts_then_runs_first_turn_immediately(self):
        port = _free_port()
        server = _WSTestServer(port)
        turn_prompts: list[str] = []

        def capturing_turn(prompt, ws, session_id, claude_session_id=None, timeout=600.0):
            turn_prompts.append(prompt)
            return "sid", 0, False

        with patch(
            "archipelago.docker_worker.headless_adapter.run_headless_turn",
            side_effect=capturing_turn,
        ):
            t = threading.Thread(
                target=run_headless_adapter,
                kwargs={"initial_prompt": "do the thing", "ws_url": f"ws://localhost:{port}"},
                daemon=True,
            )
            t.start()
            server.wait_connected()
            time.sleep(0.5)

            assert turn_prompts == ["do the thing"]
            assert "started" in server.statuses()
            assert "running" in server.statuses()

        server.send({"type": "control", "command": "terminate"})
        t.join(timeout=5)
        server.shutdown()
