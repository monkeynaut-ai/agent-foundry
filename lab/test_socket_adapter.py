"""Tests for socket-based PTY adapter using cat as a mock subprocess."""

import socket
import threading
import time

from adapter import run_socket_adapter


def _connect_with_retry(socket_path: str, timeout: float = 5.0) -> socket.socket:
    """Connect to a Unix domain socket, retrying until it's available."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(str(socket_path))
            return client
        except (ConnectionRefusedError, FileNotFoundError):
            client.close()
            time.sleep(0.05)
    raise TimeoutError(f"Could not connect to {socket_path} within {timeout}s")


class TestSocketConnection:
    """Given a socket adapter, when a client connects, then the connection succeeds."""

    def test_given_socket_adapter_when_started_then_accepts_connection(self, tmp_path):
        sock_path = str(tmp_path / "test.sock")

        adapter_thread = threading.Thread(
            target=run_socket_adapter, args=("cat", sock_path), daemon=True
        )
        adapter_thread.start()

        client = _connect_with_retry(sock_path)
        try:
            assert client.fileno() != -1
        finally:
            client.close()


class TestSocketEcho:
    """Given a connected client, when data is sent, then it is echoed back."""

    def test_given_connected_client_when_data_sent_then_echoed_back(self, tmp_path):
        sock_path = str(tmp_path / "test.sock")

        adapter_thread = threading.Thread(
            target=run_socket_adapter, args=("cat", sock_path), daemon=True
        )
        adapter_thread.start()

        client = _connect_with_retry(sock_path)
        client.settimeout(5.0)
        try:
            client.sendall(b"hello socket\n")
            data = b""
            while b"hello socket" not in data:
                chunk = client.recv(4096)
                if not chunk:
                    break
                data += chunk
            assert b"hello socket" in data
        finally:
            client.close()


class TestSocketClientDisconnect:
    """Given a connected client, when client disconnects, then adapter stops."""

    def test_given_connected_client_when_client_disconnects_then_adapter_stops(self, tmp_path):
        sock_path = str(tmp_path / "test.sock")

        adapter_thread = threading.Thread(
            target=run_socket_adapter, args=("cat", sock_path), daemon=True
        )
        adapter_thread.start()

        client = _connect_with_retry(sock_path)
        client.close()

        adapter_thread.join(timeout=5.0)
        assert not adapter_thread.is_alive()


class TestSocketChildExit:
    """Given a child process, when EOF is sent, then adapter shuts down."""

    def test_given_child_exits_when_eof_sent_then_socket_closes(self, tmp_path):
        sock_path = str(tmp_path / "test.sock")

        adapter_thread = threading.Thread(
            target=run_socket_adapter, args=("cat", sock_path), daemon=True
        )
        adapter_thread.start()

        client = _connect_with_retry(sock_path)
        client.settimeout(5.0)
        try:
            # Send Ctrl-D (EOF) to cat
            client.sendall(b"\x04")
            adapter_thread.join(timeout=5.0)
            assert not adapter_thread.is_alive()
        finally:
            client.close()
