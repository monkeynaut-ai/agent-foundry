"""Tests for ACP session manager."""

import threading
import time
from unittest.mock import MagicMock

import pytest

from agent_foundry.acp.container import ContainerHandle
from agent_foundry.acp.session import SessionHandle, SessionManager


def _mock_container_handle():
    container = MagicMock()
    container.client.api.exec_create.return_value = {"Id": "exec-abc"}
    container.client.api.exec_start.return_value = iter([])
    return ContainerHandle(
        container_id="c-123",
        status="running",
        _container=container,
    )


@pytest.fixture
def session_manager():
    return SessionManager()


class TestLaunchSession:
    def test_given_running_container_when_launch_called_then_returns_session_handle(
        self, session_manager
    ):
        handle = _mock_container_handle()
        session = session_manager.launch_session(handle, "claude -p")
        assert isinstance(session, SessionHandle)
        assert session.exec_id == "exec-abc"

    def test_given_running_container_when_launch_called_then_tty_allocated(self, session_manager):
        handle = _mock_container_handle()
        session_manager.launch_session(handle, "claude -p")
        kw = handle._container.client.api.exec_create.call_args.kwargs
        assert kw["tty"] is True
        assert kw["stdin"] is True


class TestOutputStream:
    def test_given_active_session_when_output_produced_then_callback_invoked(self):
        lines = []
        done = threading.Event()

        manager = SessionManager()
        manager.register_output_callback(
            lambda line, cid, ts: (lines.append(line), done.set() if line == "line2" else None)
        )

        handle = _mock_container_handle()
        handle._container.client.api.exec_start.return_value = iter([b"line1\nline2\n"])
        manager.launch_session(handle, "cmd")
        done.wait(timeout=2.0)

        assert "line1" in lines
        assert "line2" in lines

    def test_given_active_session_when_callback_invoked_then_tagged_with_container_id(self):
        cids = []
        done = threading.Event()

        manager = SessionManager()
        manager.register_output_callback(lambda line, cid, ts: (cids.append(cid), done.set()))

        handle = _mock_container_handle()
        handle._container.client.api.exec_start.return_value = iter([b"hi\n"])
        manager.launch_session(handle, "cmd")
        done.wait(timeout=2.0)

        assert "c-123" in cids


class TestSendInput:
    def test_given_active_session_when_send_input_called_then_written_to_stdin(
        self, session_manager
    ):
        session = SessionHandle(exec_id="e1", container_id="c1", _socket=MagicMock())
        session_manager.send_input(session, "yes\n")
        session._socket._sock.sendall.assert_called_once_with(b"yes\n")


class TestPauseResume:
    def test_given_session_when_paused_then_status_paused(self, session_manager):
        session = SessionHandle(exec_id="e1", container_id="c1")
        session_manager.pause(session)
        assert session.status == "paused"

    def test_given_paused_session_when_resumed_then_status_running(self, session_manager):
        session = SessionHandle(exec_id="e1", container_id="c1")
        session_manager.pause(session)
        session_manager.resume(session)
        assert session.status == "running"


class TestExitDetection:
    def test_given_session_when_process_exits_then_status_exited(self):
        manager = SessionManager()
        handle = _mock_container_handle()
        handle._container.client.api.exec_start.return_value = iter([])
        session = manager.launch_session(handle, "cmd")
        if manager._stream_thread:
            manager._stream_thread.join(timeout=2.0)
        assert session.status == "exited"

    def test_given_session_when_process_exits_then_exit_code_captured(self):
        manager = SessionManager()
        handle = _mock_container_handle()
        handle._container.client.api.exec_start.return_value = iter([])
        handle._container.client.api.exec_inspect.return_value = {"ExitCode": 0}
        session = manager.launch_session(handle, "cmd")
        if manager._stream_thread:
            manager._stream_thread.join(timeout=2.0)
        assert session.exit_code == 0
