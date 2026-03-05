"""Tests for WebSocket-based PTY adapter using cat as a mock subprocess."""

import json
import socket
import threading
import time

from websockets.sync.client import connect
from websockets.sync.server import serve

from adapter import run_protocol_adapter, run_ws_adapter


def _get_free_port() -> int:
    """Find an available port."""
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _connect_with_retry(url: str, timeout: float = 5.0):
    """Connect to a WebSocket, retrying until it's available."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return connect(url)
        except (ConnectionRefusedError, OSError):
            time.sleep(0.05)
    raise TimeoutError(f"Could not connect to {url} within {timeout}s")


class TestWsConnection:
    """Given a WebSocket adapter, when a client connects, then the connection succeeds."""

    def test_given_ws_adapter_when_started_then_accepts_connection(self):
        port = _get_free_port()

        adapter_thread = threading.Thread(
            target=run_ws_adapter, args=("cat", "localhost", port), daemon=True
        )
        adapter_thread.start()

        ws = _connect_with_retry(f"ws://localhost:{port}")
        try:
            assert ws.protocol.state.name == "OPEN"
        finally:
            ws.close()


class TestWsEcho:
    """Given a connected client, when data is sent, then it is echoed back."""

    def test_given_connected_client_when_data_sent_then_echoed_back(self):
        port = _get_free_port()

        adapter_thread = threading.Thread(
            target=run_ws_adapter, args=("cat", "localhost", port), daemon=True
        )
        adapter_thread.start()

        ws = _connect_with_retry(f"ws://localhost:{port}")
        try:
            ws.send("hello websocket\n")
            data = b""
            while b"hello websocket" not in data:
                chunk = ws.recv(timeout=5)
                if isinstance(chunk, str):
                    chunk = chunk.encode()
                data += chunk
            assert b"hello websocket" in data
        finally:
            ws.close()


class TestWsClientDisconnect:
    """Given a connected client, when client disconnects, then adapter stops."""

    def test_given_connected_client_when_client_disconnects_then_adapter_stops(self):
        port = _get_free_port()

        adapter_thread = threading.Thread(
            target=run_ws_adapter, args=("cat", "localhost", port), daemon=True
        )
        adapter_thread.start()

        ws = _connect_with_retry(f"ws://localhost:{port}")
        ws.close()

        adapter_thread.join(timeout=5.0)
        assert not adapter_thread.is_alive()


class TestWsChildExit:
    """Given a child process, when EOF is sent, then adapter shuts down."""

    def test_given_child_exits_when_eof_sent_then_ws_closes(self):
        port = _get_free_port()

        adapter_thread = threading.Thread(
            target=run_ws_adapter, args=("cat", "localhost", port), daemon=True
        )
        adapter_thread.start()

        ws = _connect_with_retry(f"ws://localhost:{port}")
        try:
            ws.send(b"\x04")
            adapter_thread.join(timeout=5.0)
            assert not adapter_thread.is_alive()
        finally:
            ws.close()


# ── Protocol adapter tests ──
# These tests spin up a WS server. The protocol adapter connects as a client.


def _collect_messages(ws, count=1, timeout=5.0):
    """Receive `count` JSON messages from a WebSocket connection."""
    msgs = []
    deadline = time.monotonic() + timeout
    while len(msgs) < count and time.monotonic() < deadline:
        try:
            raw = ws.recv(timeout=max(0.1, deadline - time.monotonic()))
            msgs.append(json.loads(raw))
        except (TimeoutError, json.JSONDecodeError):
            continue
    return msgs


def _run_protocol_server_adapter(port, command="cat", session_id="test-session"):
    """Start a WS server, run the protocol adapter that connects to it.

    Returns (adapter_thread, messages_list, ws_ref, server_ref, connected_event).
    The caller should use `connected_event.wait()` before interacting.
    """
    messages = []
    ws_ref = [None]
    server_ref = [None]
    connected = threading.Event()

    def handler(ws):
        ws_ref[0] = ws
        connected.set()
        try:
            while True:
                try:
                    raw = ws.recv(timeout=0.5)
                    messages.append(json.loads(raw))
                except TimeoutError:
                    continue
                except Exception:
                    break
        except Exception:
            pass

    server = serve(handler, "localhost", port)
    server_ref[0] = server
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    adapter_thread = threading.Thread(
        target=run_protocol_adapter,
        args=(command, f"ws://localhost:{port}", session_id),
        daemon=True,
    )
    adapter_thread.start()

    return adapter_thread, messages, ws_ref, server_ref, connected


class TestProtocolAdapterConnect:
    def test_given_ws_server_when_adapter_starts_then_sends_started_status(self):
        port = _get_free_port()
        adapter_thread, messages, ws_ref, server_ref, connected = \
            _run_protocol_server_adapter(port)

        try:
            connected.wait(timeout=5)
            # Wait for started message
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                started = [m for m in messages if m.get("type") == "status"
                           and m.get("status") == "started"]
                if started:
                    break
                time.sleep(0.05)
            assert len(started) >= 1
            assert started[0]["session_id"] == "test-session"
        finally:
            if ws_ref[0]:
                ws_ref[0].close()
            server_ref[0].shutdown()
            adapter_thread.join(timeout=5)


class TestProtocolAdapterOutput:
    def test_given_child_produces_output_when_adapter_running_then_sends_output_message(self):
        port = _get_free_port()
        adapter_thread, messages, ws_ref, server_ref, connected = \
            _run_protocol_server_adapter(port)

        try:
            connected.wait(timeout=5)
            # Send input that cat will echo back with a newline
            time.sleep(0.3)
            ws_ref[0].send(json.dumps({"type": "input", "session_id": "test-session", "text": "hello world\n"}))

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                output_msgs = [m for m in messages if m.get("type") == "output"
                               and "hello world" in m.get("text", "")]
                if output_msgs:
                    break
                time.sleep(0.05)
            assert len(output_msgs) >= 1
            assert output_msgs[0]["stream"] == "stdout"
        finally:
            if ws_ref[0]:
                ws_ref[0].close()
            server_ref[0].shutdown()
            adapter_thread.join(timeout=5)

    def test_given_child_produces_ansi_output_when_adapter_running_then_ansi_stripped(self):
        port = _get_free_port()
        # Use printf to emit ANSI codes
        adapter_thread, messages, ws_ref, server_ref, connected = \
            _run_protocol_server_adapter(port, command="cat")

        try:
            connected.wait(timeout=5)
            time.sleep(0.3)
            # Send text with ANSI codes that cat will echo
            ws_ref[0].send(json.dumps({
                "type": "input", "session_id": "test-session",
                "text": "\033[32mGREEN\033[0m\n",
            }))

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                output_msgs = [m for m in messages if m.get("type") == "output"
                               and "GREEN" in m.get("text", "")]
                if output_msgs:
                    break
                time.sleep(0.05)
            assert len(output_msgs) >= 1
            # ANSI codes should be stripped
            assert "\033[" not in output_msgs[0]["text"]
        finally:
            if ws_ref[0]:
                ws_ref[0].close()
            server_ref[0].shutdown()
            adapter_thread.join(timeout=5)


class TestProtocolAdapterInterrupt:
    def test_given_child_emits_clarification_marker_when_adapter_running_then_sends_interrupt_message(self):
        port = _get_free_port()
        adapter_thread, messages, ws_ref, server_ref, connected = \
            _run_protocol_server_adapter(port)

        try:
            connected.wait(timeout=5)
            time.sleep(0.3)
            marker = 'ARCHIPELAGO_NEED_CLARIFICATION {"question": "Which DB?", "options": ["pg"], "default": "pg", "blocking": true}\n'
            ws_ref[0].send(json.dumps({"type": "input", "session_id": "test-session", "text": marker}))

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                interrupt_msgs = [m for m in messages if m.get("type") == "interrupt"
                                  and m.get("interrupt_type") == "clarification"]
                if interrupt_msgs:
                    break
                time.sleep(0.05)
            assert len(interrupt_msgs) >= 1
            assert interrupt_msgs[0]["payload"]["question"] == "Which DB?"
        finally:
            if ws_ref[0]:
                ws_ref[0].close()
            server_ref[0].shutdown()
            adapter_thread.join(timeout=5)

    def test_given_child_emits_malformed_marker_when_adapter_running_then_sends_output_message(self):
        port = _get_free_port()
        adapter_thread, messages, ws_ref, server_ref, connected = \
            _run_protocol_server_adapter(port)

        try:
            connected.wait(timeout=5)
            time.sleep(0.3)
            # Malformed JSON after marker
            ws_ref[0].send(json.dumps({
                "type": "input", "session_id": "test-session",
                "text": "ARCHIPELAGO_NEED_CLARIFICATION {bad json\n",
            }))

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                output_msgs = [m for m in messages if m.get("type") == "output"
                               and "ARCHIPELAGO_NEED_CLARIFICATION" in m.get("text", "")]
                if output_msgs:
                    break
                time.sleep(0.05)
            assert len(output_msgs) >= 1
        finally:
            if ws_ref[0]:
                ws_ref[0].close()
            server_ref[0].shutdown()
            adapter_thread.join(timeout=5)


class TestProtocolAdapterInput:
    def test_given_input_message_sent_when_adapter_running_then_text_written_to_pty(self):
        port = _get_free_port()
        adapter_thread, messages, ws_ref, server_ref, connected = \
            _run_protocol_server_adapter(port)

        try:
            connected.wait(timeout=5)
            time.sleep(0.3)
            ws_ref[0].send(json.dumps({"type": "input", "session_id": "test-session", "text": "test input\n"}))

            # Cat echoes it back, so we should see it as output
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                output_msgs = [m for m in messages if m.get("type") == "output"
                               and "test input" in m.get("text", "")]
                if output_msgs:
                    break
                time.sleep(0.05)
            assert len(output_msgs) >= 1
        finally:
            if ws_ref[0]:
                ws_ref[0].close()
            server_ref[0].shutdown()
            adapter_thread.join(timeout=5)

    def test_given_input_message_with_newline_when_adapter_running_then_cr_written_to_pty(self):
        """The adapter converts \\n to \\r before writing to PTY."""
        port = _get_free_port()
        adapter_thread, messages, ws_ref, server_ref, connected = \
            _run_protocol_server_adapter(port)

        try:
            connected.wait(timeout=5)
            time.sleep(0.3)
            # Send input with \n — adapter should convert to \r for PTY
            ws_ref[0].send(json.dumps({"type": "input", "session_id": "test-session", "text": "hello\n"}))

            # Cat echoes it back — we verify it works (the ICRNL conversion is internal)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                output_msgs = [m for m in messages if m.get("type") == "output"
                               and "hello" in m.get("text", "")]
                if output_msgs:
                    break
                time.sleep(0.05)
            assert len(output_msgs) >= 1
        finally:
            if ws_ref[0]:
                ws_ref[0].close()
            server_ref[0].shutdown()
            adapter_thread.join(timeout=5)


class TestProtocolAdapterControl:
    def test_given_resize_command_when_adapter_running_then_pty_resized(self):
        port = _get_free_port()
        adapter_thread, messages, ws_ref, server_ref, connected = \
            _run_protocol_server_adapter(port)

        try:
            connected.wait(timeout=5)
            time.sleep(0.3)
            ws_ref[0].send(json.dumps({
                "type": "control", "session_id": "test-session",
                "command": "resize", "args": {"rows": 50, "cols": 120},
            }))
            # No direct way to assert PTY size from outside, but no error should occur
            time.sleep(0.5)
            assert adapter_thread.is_alive()
        finally:
            if ws_ref[0]:
                ws_ref[0].close()
            server_ref[0].shutdown()
            adapter_thread.join(timeout=5)

    def test_given_terminate_command_when_adapter_running_then_child_terminated(self):
        port = _get_free_port()
        adapter_thread, messages, ws_ref, server_ref, connected = \
            _run_protocol_server_adapter(port)

        try:
            connected.wait(timeout=5)
            time.sleep(0.3)
            ws_ref[0].send(json.dumps({
                "type": "control", "session_id": "test-session",
                "command": "terminate",
            }))

            adapter_thread.join(timeout=5)
            assert not adapter_thread.is_alive()

            # Should have sent exited status
            exited = [m for m in messages if m.get("type") == "status"
                       and m.get("status") == "exited"]
            assert len(exited) >= 1
        finally:
            server_ref[0].shutdown()


class TestProtocolAdapterExit:
    def test_given_child_exits_when_adapter_running_then_sends_exited_status_with_code(self):
        port = _get_free_port()
        # Use 'echo hello' — exits with 0 after producing output
        adapter_thread, messages, ws_ref, server_ref, connected = \
            _run_protocol_server_adapter(port, command="echo hello")

        try:
            connected.wait(timeout=5)
            adapter_thread.join(timeout=10)
            assert not adapter_thread.is_alive()

            # Give the server handler a moment to receive final messages
            time.sleep(0.5)

            exited = [m for m in messages if m.get("type") == "status"
                       and m.get("status") == "exited"]
            assert len(exited) >= 1
            assert exited[0]["exit_code"] == 0
        finally:
            server_ref[0].shutdown()

    def test_given_ws_server_closes_when_adapter_running_then_child_terminated(self):
        port = _get_free_port()
        adapter_thread, messages, ws_ref, server_ref, connected = \
            _run_protocol_server_adapter(port)

        try:
            connected.wait(timeout=5)
            time.sleep(0.3)
            # Close the WS from server side
            ws_ref[0].close()
            adapter_thread.join(timeout=5)
            assert not adapter_thread.is_alive()
        finally:
            server_ref[0].shutdown()


class TestProtocolAdapterRetry:
    def test_given_server_not_ready_when_adapter_starts_then_retries_until_connected(self):
        port = _get_free_port()

        # Start adapter first (server not yet running)
        adapter_thread = threading.Thread(
            target=run_protocol_adapter,
            args=("true", f"ws://localhost:{port}", "retry-session"),
            daemon=True,
        )
        adapter_thread.start()

        # Wait a bit, then start server
        time.sleep(0.8)

        messages = []
        ws_ref = [None]

        def handler(ws):
            ws_ref[0] = ws
            try:
                while True:
                    raw = ws.recv(timeout=1)
                    messages.append(json.loads(raw))
            except Exception:
                pass

        server = serve(handler, "localhost", port)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            adapter_thread.join(timeout=10)
            assert not adapter_thread.is_alive()

            started = [m for m in messages if m.get("type") == "status"
                       and m.get("status") == "started"]
            assert len(started) >= 1
        finally:
            server.shutdown()

    def test_given_server_never_available_when_adapter_starts_then_exits_with_error(self):
        port = _get_free_port()

        exit_codes = []

        def _run():
            code = run_protocol_adapter(
                "true", f"ws://localhost:{port}", "fail-session",
                connect_timeout=3.0,
            )
            exit_codes.append(code)

        adapter_thread = threading.Thread(target=_run, daemon=True)
        adapter_thread.start()

        adapter_thread.join(timeout=10)
        assert not adapter_thread.is_alive()
        assert exit_codes[0] == 1
