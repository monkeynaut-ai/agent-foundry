"""Docker worker handler — unit tests with mocked Docker and WebSocket protocol."""

import contextlib
import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.planner.validators import validate_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from archipelago.docker_worker.handler import (
    _HandlerWSServer,
    docker_worker_handler,
)
from archipelago.docker_worker.models import WorkerConstraints, WorkerResult
from archipelago.docker_worker.protocol import (
    AgentEventMessage,
    OutputMessage,
    StatusMessage,
)

PLAN_PATH = Path(__file__).parent.parent.parent / "src" / "archipelago" / "archipelago_system.json"


@pytest.fixture
def plan():
    plan_data = json.loads(PLAN_PATH.read_text())
    return GraphWiringPlan(**plan_data)


def _valid_worker_input() -> dict:
    return {
        "repo_ref": "abc123",
        "feature_spec": {"title": "Test"},
        "constraints": WorkerConstraints().model_dump(),
        "test_commands": ["pytest"],
        "gates": [],
    }


class DockerTestHelper:
    """Encapsulates the multi-level mock chain for Docker handler tests."""

    def __init__(self, mock_docker):
        self.client = MagicMock()
        self.container = MagicMock()
        self.container.id = "c1"
        self.container.exec_run.return_value = (0, b"/home/claude/.local/bin/claude")
        self.client.containers.create.return_value = self.container
        mock_docker.from_env.return_value = self.client


def _mock_docker_env(mock_docker):
    """Create a standard mock Docker client/container for handler tests."""
    helper = DockerTestHelper(mock_docker)
    return helper.client, helper.container


def _preload_ws_server(messages: list[str]):
    """Create a mock _HandlerWSServer with pre-loaded messages and pre-set connected."""
    server = MagicMock(spec=_HandlerWSServer)
    q = __import__("queue").Queue()
    for m in messages:
        q.put(m)
    server.message_queue = q
    server.connected = threading.Event()
    server.connected.set()
    server.send = MagicMock()
    server.start = MagicMock()
    server.shutdown = MagicMock()
    return server


def _output_msg(text: str, session_id: str = "test") -> str:
    return OutputMessage(
        type="output",
        session_id=session_id,
        text=text,
        stream="stdout",
        timestamp=1.0,
    ).model_dump_json()


def _status_msg(status: str, exit_code: int | None = None, session_id: str = "test") -> str:
    return StatusMessage(
        type="status",
        session_id=session_id,
        status=status,
        exit_code=exit_code,
        timestamp=1.0,
    ).model_dump_json()


def _interrupt_msg(
    event_type: str,
    payload: dict,
    session_id: str = "test",
) -> str:
    return AgentEventMessage(
        session_id=session_id,
        event_type=event_type,
        payload=payload,
        raw_line="raw",
        timestamp=1.0,
    ).model_dump_json()


class TestDockerWorkerHandler:
    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_valid_worker_input_when_called_then_container_created_and_started(
        self, mock_docker, mock_ws_cls
    ):
        mock_client, _ = _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server([_status_msg("exited", 0)])

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        mock_client.containers.create.assert_called_once()
        assert "worker_result" in result

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_valid_worker_input_when_called_then_ws_server_started(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        ws_server = _preload_ws_server([_status_msg("exited", 0)])
        mock_ws_cls.return_value = ws_server

        state = {"worker_input": _valid_worker_input()}
        docker_worker_handler(state)
        ws_server.start.assert_called_once()

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_successful_cc_run_when_called_then_worker_result_returned(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server(
            [
                _output_msg("done"),
                _status_msg("exited", 0),
            ]
        )

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        assert result["worker_result"] is not None
        assert result["worker_result"]["status"] in ("completed", "failed")

    @patch("archipelago.docker_worker.handler.docker")
    def test_given_docker_unavailable_when_called_then_status_is_failed(self, mock_docker):
        mock_docker.from_env.side_effect = Exception("Docker not running")

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        assert result["worker_result"]["status"] == "failed"
        assert "Docker unavailable" in result["worker_result"]["result_summary"]

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_handler_completes_when_called_then_container_destroyed(
        self, mock_docker, mock_ws_cls
    ):
        _, mock_container = _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server([_status_msg("exited", 0)])

        state = {"worker_input": _valid_worker_input()}
        docker_worker_handler(state)
        mock_container.remove.assert_called_once()

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_successful_cc_run_when_called_then_worker_result_validates(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server(
            [
                _output_msg("done"),
                _status_msg("exited", 0),
            ]
        )

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        worker_result = WorkerResult(**result["worker_result"])
        assert worker_result.status in ("completed", "failed")
        assert isinstance(worker_result.patches, list)
        assert isinstance(worker_result.evidence, list)

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_cc_timeout_when_called_then_status_is_timed_out(self, mock_docker, mock_ws_cls):
        _mock_docker_env(mock_docker)
        # Only output, no exited status — will timeout
        mock_ws_cls.return_value = _preload_ws_server([_output_msg("working...")])

        worker_input = _valid_worker_input()
        worker_input["constraints"]["timeout_seconds"] = 0
        state = {"worker_input": worker_input}
        result = docker_worker_handler(state)
        assert result["worker_result"]["status"] == "timed_out"

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_interrupt_during_run_when_called_then_breakpoint_payload_set(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server(
            [
                _interrupt_msg(
                    "clarification_requested",
                    {
                        "question": "Which DB?",
                        "options": ["pg"],
                        "default": "pg",
                        "blocking": True,
                    },
                ),
            ]
        )

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        assert result.get("breakpoint_payload") is not None
        assert result["breakpoint_payload"]["type"] == "clarification"
        assert result["worker_result"] is None

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_successful_cc_run_when_called_then_progress_read_from_container(
        self, mock_docker, mock_ws_cls
    ):
        _, mock_container = _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server(
            [
                _output_msg("done"),
                _status_msg("exited", 0),
            ]
        )

        state = {"worker_input": _valid_worker_input()}
        docker_worker_handler(state)
        get_archive_calls = [
            c for c in mock_container.get_archive.call_args_list if "progress.jsonl" in str(c)
        ]
        assert len(get_archive_calls) > 0

    @patch("archipelago.docker_worker.handler.persist_workspace_state")
    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_cc_crash_when_called_then_workspace_state_persisted(
        self, mock_docker, mock_ws_cls, mock_persist
    ):
        _mock_docker_env(mock_docker)
        # Connected event never set → TimeoutError → crash path
        ws_server = _preload_ws_server([])
        ws_server.connected = threading.Event()  # NOT set
        mock_ws_cls.return_value = ws_server

        worker_input = _valid_worker_input()
        worker_input["constraints"]["connection_timeout_seconds"] = 0
        state = {"worker_input": worker_input}
        result = docker_worker_handler(state)

        assert result["worker_result"]["status"] == "failed"
        mock_persist.assert_called_once()

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_no_worker_input_when_state_has_feature_spec_then_worker_input_constructed(
        self, mock_docker, mock_ws_cls
    ):
        mock_client, _ = _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server([_status_msg("exited", 0)])

        state = {
            "repo_ref": "abc123",
            "feature_spec": {"title": "Test Feature"},
            "worker_constraints": {},
            "test_commands": ["pytest"],
            "gates": [],
        }
        result = docker_worker_handler(state)
        mock_client.containers.create.assert_called_once()
        assert "worker_result" in result

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_no_worker_input_when_defaults_used_then_worker_input_constructed(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server([_status_msg("exited", 0)])

        state = {"feature_spec": {"title": "Minimal"}}
        result = docker_worker_handler(state)
        assert "worker_result" in result

    def test_given_entrypoint_when_read_then_contains_archipelago_ws_url_check(self):
        """Entrypoint launches adapter when ARCHIPELAGO_WS_URL is set."""
        entrypoint = (
            Path(__file__).parent.parent.parent
            / "src"
            / "agent_foundry"
            / "acp"
            / "docker"
            / "entrypoint.sh"
        )
        content = entrypoint.read_text()
        assert "ARCHIPELAGO_WS_URL" in content
        assert "adapter.py" in content

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_turn_timeout_seconds_in_constraints_when_called_then_archipelago_turn_timeout_env_passed(
        self, mock_docker, mock_ws_cls
    ):
        mock_client, _ = _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server([_status_msg("exited", 0)])

        worker_input = _valid_worker_input()
        worker_input["constraints"]["turn_timeout_seconds"] = 7200
        docker_worker_handler({"worker_input": worker_input})

        env = mock_client.containers.create.call_args.kwargs["environment"]
        assert env["ARCHIPELAGO_TURN_TIMEOUT"] == "7200"

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_skip_permissions_true_when_called_then_archipelago_skip_permissions_is_1(
        self, mock_docker, mock_ws_cls
    ):
        mock_client, _ = _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server([_status_msg("exited", 0)])

        worker_input = _valid_worker_input()
        worker_input["constraints"]["skip_permissions"] = True
        docker_worker_handler({"worker_input": worker_input})

        env = mock_client.containers.create.call_args.kwargs["environment"]
        assert env["ARCHIPELAGO_SKIP_PERMISSIONS"] == "1"

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_skip_permissions_false_when_called_then_archipelago_skip_permissions_is_0(
        self, mock_docker, mock_ws_cls
    ):
        mock_client, _ = _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server([_status_msg("exited", 0)])

        worker_input = _valid_worker_input()
        worker_input["constraints"]["skip_permissions"] = False
        docker_worker_handler({"worker_input": worker_input})

        env = mock_client.containers.create.call_args.kwargs["environment"]
        assert env["ARCHIPELAGO_SKIP_PERMISSIONS"] == "0"

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_worker_input_with_repo_url_when_called_then_repo_url_and_ref_passed_as_container_env(
        self, mock_docker, mock_ws_cls
    ):
        mock_client, _ = _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server([_status_msg("exited", 0)])

        worker_input = _valid_worker_input()
        worker_input["repo_url"] = "https://github.com/org/repo"
        worker_input["repo_ref"] = "feat/my-branch"
        docker_worker_handler({"worker_input": worker_input})

        call_kwargs = mock_client.containers.create.call_args
        env = call_kwargs.kwargs["environment"]
        assert env["REPO_URL"] == "https://github.com/org/repo"
        assert env["REPO_REF"] == "feat/my-branch"


class TestEntrypointProvisioning:
    def test_given_entrypoint_when_read_then_writes_netrc_when_github_token_set(self):
        entrypoint = (
            Path(__file__).parent.parent.parent
            / "src"
            / "agent_foundry"
            / "acp"
            / "docker"
            / "entrypoint.sh"
        )
        content = entrypoint.read_text()
        assert "GITHUB_TOKEN" in content
        assert ".netrc" in content

    def test_given_entrypoint_when_read_then_clones_from_repo_url_when_workspace_empty(self):
        entrypoint = (
            Path(__file__).parent.parent.parent
            / "src"
            / "agent_foundry"
            / "acp"
            / "docker"
            / "entrypoint.sh"
        )
        content = entrypoint.read_text()
        assert "REPO_URL" in content
        assert "git clone" in content
        assert ".git" in content  # skips clone if workspace already has a repo

    def test_given_entrypoint_when_read_then_uses_repo_ref_as_branch(self):
        entrypoint = (
            Path(__file__).parent.parent.parent
            / "src"
            / "agent_foundry"
            / "acp"
            / "docker"
            / "entrypoint.sh"
        )
        content = entrypoint.read_text()
        assert "REPO_REF" in content

    def test_given_entrypoint_when_read_then_netrc_written_before_clone(self):
        entrypoint = (
            Path(__file__).parent.parent.parent
            / "src"
            / "agent_foundry"
            / "acp"
            / "docker"
            / "entrypoint.sh"
        )
        content = entrypoint.read_text()
        assert content.index(".netrc") < content.index("git clone")

    def test_given_entrypoint_when_read_then_passes_turn_timeout_to_adapter(self):
        entrypoint = (
            Path(__file__).parent.parent.parent
            / "src"
            / "agent_foundry"
            / "acp"
            / "docker"
            / "entrypoint.sh"
        )
        content = entrypoint.read_text()
        assert "ARCHIPELAGO_TURN_TIMEOUT" in content
        assert "--timeout" in content

    def test_given_entrypoint_when_read_then_conditionally_passes_dangerously_skip_permissions(
        self,
    ):
        entrypoint = (
            Path(__file__).parent.parent.parent
            / "src"
            / "agent_foundry"
            / "acp"
            / "docker"
            / "entrypoint.sh"
        )
        content = entrypoint.read_text()
        assert "ARCHIPELAGO_SKIP_PERMISSIONS" in content
        assert "--dangerously-skip-permissions" in content


class TestHandlerProtocol:
    """Tests for WebSocket protocol message handling in the handler."""

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_adapter_sends_output_when_handler_running_then_output_collected(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server(
            [
                _output_msg("line 1"),
                _output_msg("line 2"),
                _status_msg("exited", 0),
            ]
        )

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        assert "2 output lines" in result["worker_result"]["result_summary"]

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_adapter_sends_clarification_interrupt_when_handler_running_then_breakpoint_set(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server(
            [
                _interrupt_msg(
                    "clarification_requested",
                    {
                        "question": "Which DB?",
                        "options": ["pg"],
                        "default": "pg",
                        "blocking": True,
                    },
                ),
            ]
        )

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        assert result["breakpoint_payload"]["type"] == "clarification"
        assert result["breakpoint_payload"]["question"] == "Which DB?"

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_adapter_sends_permission_interrupt_with_auto_approve_when_handler_running_then_input_sent(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        ws_server = _preload_ws_server(
            [
                _interrupt_msg(
                    "permission_requested",
                    {
                        "action": "delete file",
                        "risk_level": "low",
                        "why_needed": "cleanup",
                    },
                ),
                _status_msg("exited", 0),
            ]
        )
        mock_ws_cls.return_value = ws_server

        # Enable auto-approve by setting network_policy != "none"
        worker_input = _valid_worker_input()
        worker_input["constraints"]["network_policy"] = "egress"
        state = {"worker_input": worker_input}
        result = docker_worker_handler(state)

        # Should have auto-approved (sent "yes\n") and completed
        assert result["worker_result"]["status"] in ("completed", "failed")
        send_calls = ws_server.send.call_args_list
        input_msgs = []
        for c in send_calls:
            try:
                msg = json.loads(c[0][0])
                if msg.get("type") == "input" and "yes" in msg.get("text", ""):
                    input_msgs.append(msg)
            except (json.JSONDecodeError, IndexError):
                pass
        assert len(input_msgs) >= 1

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_adapter_sends_update_available_when_handler_running_then_recorded_in_state(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server(
            [
                _interrupt_msg(
                    "update_available",
                    {
                        "installed": "1.0.0",
                        "latest": "1.1.0",
                    },
                ),
                _status_msg("exited", 0),
            ]
        )

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        assert result["update_available"]["installed"] == "1.0.0"
        assert result["update_available"]["latest"] == "1.1.0"

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_adapter_sends_exited_status_when_handler_running_then_result_returned(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server(
            [
                _output_msg("done"),
                _status_msg("exited", 0),
            ]
        )

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        assert result["worker_result"]["status"] == "completed"

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_adapter_sends_completed_status_when_handler_running_then_result_is_completed(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server(
            [
                _output_msg("All tests pass"),
                _status_msg("completed", 0),
            ]
        )

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        assert result["worker_result"]["status"] == "completed"

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_adapter_sends_completed_status_when_handler_running_then_loop_exits_before_timeout(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        worker_input = _valid_worker_input()
        worker_input["constraints"]["timeout_seconds"] = 3600
        mock_ws_cls.return_value = _preload_ws_server([_status_msg("completed", 0)])

        state = {"worker_input": worker_input}
        result = docker_worker_handler(state)
        assert result["worker_result"]["status"] == "completed"

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_ws_connection_drops_when_handler_running_then_result_is_failed(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        # None sentinel = connection dropped
        mock_ws_cls.return_value = _preload_ws_server([None])

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        assert result["worker_result"]["status"] == "failed"

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_handler_timeout_when_session_running_then_terminate_sent(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        ws_server = _preload_ws_server([_output_msg("working...")])
        mock_ws_cls.return_value = ws_server

        worker_input = _valid_worker_input()
        worker_input["constraints"]["timeout_seconds"] = 0
        state = {"worker_input": worker_input}
        result = docker_worker_handler(state)

        assert result["worker_result"]["status"] == "timed_out"
        # Should have sent terminate control message
        send_calls = ws_server.send.call_args_list
        control_msgs = []
        for c in send_calls:
            try:
                msg = json.loads(c[0][0])
                if msg.get("type") == "control" and msg.get("command") == "terminate":
                    control_msgs.append(msg)
            except (json.JSONDecodeError, IndexError):
                pass
        assert len(control_msgs) >= 1

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_adapter_connects_when_handler_runs_then_feature_spec_sent_as_input_message(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        ws_server = _preload_ws_server([_status_msg("exited", 0)])
        mock_ws_cls.return_value = ws_server

        docker_worker_handler({"worker_input": _valid_worker_input()})

        input_msgs = []
        for c in ws_server.send.call_args_list:
            with contextlib.suppress(Exception):
                msg = json.loads(c[0][0])
                if msg.get("type") == "input":
                    input_msgs.append(msg)

        assert len(input_msgs) == 1
        assert "Implement the following feature:" in input_msgs[0]["text"]
        assert "Test" in input_msgs[0]["text"]

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_adapter_connects_when_handler_runs_then_no_blank_newline_input_sent(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        ws_server = _preload_ws_server([_status_msg("exited", 0)])
        mock_ws_cls.return_value = ws_server

        docker_worker_handler({"worker_input": _valid_worker_input()})

        for c in ws_server.send.call_args_list:
            with contextlib.suppress(Exception):
                msg = json.loads(c[0][0])
                if msg.get("type") == "input":
                    assert msg["text"].strip(), "Blank input message sent to adapter"


class TestProtocolEndToEnd:
    """End-to-end test: real _HandlerWSServer, mock WS client simulating adapter, mocked Docker."""

    @patch("archipelago.docker_worker.handler.docker")
    def test_given_mocked_adapter_when_full_lifecycle_runs_then_handler_returns_valid_result(
        self, mock_docker
    ):
        import socket as _socket
        import time as _time

        from websockets.sync.client import connect as ws_client_connect

        _mock_docker_env(mock_docker)

        # Find a port we control so we can connect our mock adapter
        with _socket.socket() as s:
            s.bind(("", 0))
            known_port = s.getsockname()[1]

        # Patch _get_free_port to return our known port
        with patch("archipelago.docker_worker.handler._get_free_port", return_value=known_port):
            result_holder = []

            def _run_handler():
                state = {"worker_input": _valid_worker_input()}
                result_holder.append(docker_worker_handler(state))

            handler_thread = threading.Thread(target=_run_handler, daemon=True)
            handler_thread.start()

            # Wait for WS server to be ready, then connect
            deadline = _time.monotonic() + 5
            ws = None
            while _time.monotonic() < deadline:
                try:
                    ws = ws_client_connect(f"ws://localhost:{known_port}/test")
                    break
                except (ConnectionRefusedError, OSError):
                    _time.sleep(0.05)
            assert ws is not None, "Could not connect to handler WS server"

            try:
                # Send protocol messages simulating adapter
                ws.send(
                    StatusMessage(
                        type="status",
                        session_id="test",
                        status="started",
                        timestamp=_time.time(),
                    ).model_dump_json()
                )

                ws.send(
                    OutputMessage(
                        type="output",
                        session_id="test",
                        text="Running tests...",
                        stream="stdout",
                        timestamp=_time.time(),
                    ).model_dump_json()
                )

                ws.send(
                    OutputMessage(
                        type="output",
                        session_id="test",
                        text="All tests passed",
                        stream="stdout",
                        timestamp=_time.time(),
                    ).model_dump_json()
                )

                ws.send(
                    StatusMessage(
                        type="status",
                        session_id="test",
                        status="exited",
                        exit_code=0,
                        timestamp=_time.time(),
                    ).model_dump_json()
                )
            finally:
                _time.sleep(0.5)
                with contextlib.suppress(Exception):
                    ws.close()

            handler_thread.join(timeout=10)
            assert not handler_thread.is_alive()
            assert len(result_holder) == 1

            result = result_holder[0]
            worker_result = WorkerResult(**result["worker_result"])
            assert worker_result.status == "completed"
            assert "2 output lines" in worker_result.result_summary


class TestPipelineIntegration:
    def test_given_updated_plan_when_validated_then_all_7_checks_pass(self, plan, registry):
        validate_plan(plan, registry)

    def test_given_handler_registry_with_docker_worker_when_compile_plan_called_then_compiles(
        self, plan, registry
    ):
        def _stub(state: dict[str, Any]) -> dict[str, Any]:
            return state

        handlers = {
            "strategy_generate_product_brief": _stub,
            "architecture_generate_feature_arch": _stub,
            "spec_generate_feature_spec": _stub,
            "human_approval_gate": _stub,
            "coding_implement_feature_from_spec": _stub,
        }
        graph = compile_plan(plan, registry, handler_registry=handlers)
        assert graph is not None
