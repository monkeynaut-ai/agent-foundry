"""Tests for WebSocket-based PTY adapter using cat as a mock subprocess."""

import socket
import threading
import time

from websockets.sync.client import connect

from adapter import run_ws_adapter


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
