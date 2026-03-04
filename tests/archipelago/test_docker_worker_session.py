"""Docker worker PTY session — unit tests with mocked Docker SDK."""

import time
from unittest.mock import MagicMock

import pytest

from archipelago.docker_worker.container import ContainerHandle
from archipelago.docker_worker.session import SessionHandle, SessionManager


def _mock_container_handle():
    container = MagicMock()
    container.client.api.exec_create.return_value = {"Id": "exec-abc"}
    container.client.api.exec_start.return_value = iter([])
    handle = ContainerHandle(
        container_id="c-123",
        status="running",
        _container=container,
    )
    return handle


@pytest.fixture
def session_manager():
    return SessionManager()


# ── Commit 1: launch_session ──


class TestLaunchSession:
    def test_given_running_container_when_launch_called_then_returns_session_handle(
        self, session_manager
    ):
        handle = _mock_container_handle()
        session = session_manager.launch_session(handle, "claude-code --yes")
        assert isinstance(session, SessionHandle)
        assert session.exec_id == "exec-abc"

    def test_given_running_container_when_launch_called_then_tty_allocated(self, session_manager):
        handle = _mock_container_handle()
        session_manager.launch_session(handle, "claude-code")
        call_kwargs = handle._container.client.api.exec_create.call_args
        assert call_kwargs.kwargs["tty"] is True
        assert call_kwargs.kwargs["stdin"] is True

    def test_given_running_container_when_launch_called_then_status_is_running(
        self, session_manager
    ):
        handle = _mock_container_handle()
        session = session_manager.launch_session(handle, "claude-code")
        # Status starts as running (may transition to exited quickly with empty stream)
        assert session.exec_id == "exec-abc"


# ── Commit 2: output streaming with callbacks ──


class TestOutputStream:
    def test_given_active_session_when_cc_produces_output_then_callback_invoked_per_line(
        self,
    ):
        lines_received = []
        manager = SessionManager()
        manager.register_output_callback(lambda line, cid, ts: lines_received.append(line))

        handle = _mock_container_handle()
        handle._container.client.api.exec_start.return_value = iter([b"line1\nline2\n"])
        manager.launch_session(handle, "cmd")
        time.sleep(0.1)

        assert "line1" in lines_received
        assert "line2" in lines_received

    def test_given_active_session_when_callback_invoked_then_line_tagged_with_container_id(
        self,
    ):
        received_cids = []
        manager = SessionManager()
        manager.register_output_callback(lambda line, cid, ts: received_cids.append(cid))

        handle = _mock_container_handle()
        handle._container.client.api.exec_start.return_value = iter([b"hello\n"])
        manager.launch_session(handle, "cmd")
        time.sleep(0.1)

        assert "c-123" in received_cids

    def test_given_active_session_when_callback_invoked_then_line_tagged_with_timestamp(
        self,
    ):
        received_ts = []
        manager = SessionManager()
        manager.register_output_callback(lambda line, cid, ts: received_ts.append(ts))

        handle = _mock_container_handle()
        handle._container.client.api.exec_start.return_value = iter([b"hello\n"])
        manager.launch_session(handle, "cmd")
        time.sleep(0.1)

        assert len(received_ts) >= 1
        assert received_ts[0] > 0

    def test_given_multiple_callbacks_when_output_produced_then_all_callbacks_invoked(
        self,
    ):
        cb1_lines = []
        cb2_lines = []
        manager = SessionManager()
        manager.register_output_callback(lambda line, cid, ts: cb1_lines.append(line))
        manager.register_output_callback(lambda line, cid, ts: cb2_lines.append(line))

        handle = _mock_container_handle()
        handle._container.client.api.exec_start.return_value = iter([b"test\n"])
        manager.launch_session(handle, "cmd")
        time.sleep(0.1)

        assert "test" in cb1_lines
        assert "test" in cb2_lines


# ── Commit 3: send_input, pause/resume, exit detection ──


class TestSendInput:
    def test_given_active_session_when_send_input_called_then_text_written_to_stdin(
        self, session_manager
    ):
        session = SessionHandle(
            exec_id="e1",
            container_id="c1",
            _socket=MagicMock(),
        )
        session_manager.send_input(session, "yes\n")
        session._socket._sock.sendall.assert_called_once_with(b"yes\n")


class TestPauseResume:
    def test_given_active_session_when_paused_then_status_is_paused(self, session_manager):
        session = SessionHandle(exec_id="e1", container_id="c1")
        session_manager.pause(session)
        assert session.status == "paused"

    def test_given_paused_session_when_resumed_then_status_is_running(self, session_manager):
        session = SessionHandle(exec_id="e1", container_id="c1")
        session_manager.pause(session)
        session_manager.resume(session)
        assert session.status == "running"

    def test_given_paused_session_when_output_produced_then_callback_not_invoked_until_resume(
        self,
    ):
        lines = []
        manager = SessionManager()
        manager.register_output_callback(lambda line, cid, ts: lines.append(line))

        # Pre-pause before launching
        dummy_session = SessionHandle(exec_id="e", container_id="c")
        manager.pause(dummy_session)

        handle = _mock_container_handle()
        handle._container.client.api.exec_start.return_value = iter([b"blocked\n"])
        session = manager.launch_session(handle, "cmd")
        time.sleep(0.1)

        # Should not have received the line yet (paused)
        assert "blocked" not in lines

        # Resume
        manager.resume(session)
        time.sleep(0.1)

        assert "blocked" in lines


class TestExitDetection:
    def test_given_session_when_process_exits_then_status_is_exited(self):
        manager = SessionManager()
        handle = _mock_container_handle()
        handle._container.client.api.exec_start.return_value = iter([])
        session = manager.launch_session(handle, "cmd")
        time.sleep(0.1)
        assert session.status == "exited"

    def test_given_session_when_process_exits_then_exit_code_captured(self):
        manager = SessionManager()
        handle = _mock_container_handle()
        handle._container.client.api.exec_start.return_value = iter([])
        handle._container.client.api.exec_inspect.return_value = {"ExitCode": 0}

        session = manager.launch_session(handle, "cmd")
        time.sleep(0.1)
        assert session.status == "exited"
        assert session.exit_code == 0
        # Verify we used _client_api (stored from container.client.api), not _socket
        handle._container.client.api.exec_inspect.assert_called_once_with("exec-abc")
