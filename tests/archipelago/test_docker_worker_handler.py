"""Docker worker handler — unit tests with mocked Docker and WebSocket protocol."""

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
    InputMessage,
    InterruptMessage,
    OutputMessage,
    StatusMessage,
)

PLAN_PATH = Path(__file__).parent.parent.parent / "src" / "archipelago" / "pipeline_plan.json"


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
        type="output", session_id=session_id, text=text,
        stream="stdout", timestamp=1.0,
    ).model_dump_json()


def _status_msg(status: str, exit_code: int | None = None, session_id: str = "test") -> str:
    return StatusMessage(
        type="status", session_id=session_id, status=status,
        exit_code=exit_code, timestamp=1.0,
    ).model_dump_json()


def _interrupt_msg(
    interrupt_type: str, payload: dict, session_id: str = "test",
) -> str:
    return InterruptMessage(
        type="interrupt", session_id=session_id,
        interrupt_type=interrupt_type, payload=payload,
        raw_line="raw", timestamp=1.0,
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
        mock_ws_cls.return_value = _preload_ws_server([
            _output_msg("done"),
            _status_msg("exited", 0),
        ])

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
        mock_ws_cls.return_value = _preload_ws_server([
            _output_msg("done"),
            _status_msg("exited", 0),
        ])

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        worker_result = WorkerResult(**result["worker_result"])
        assert worker_result.status in ("completed", "failed")
        assert isinstance(worker_result.patches, list)
        assert isinstance(worker_result.evidence, list)

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_cc_timeout_when_called_then_status_is_timed_out(
        self, mock_docker, mock_ws_cls
    ):
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
        mock_ws_cls.return_value = _preload_ws_server([
            _interrupt_msg("clarification", {
                "question": "Which DB?", "options": ["pg"],
                "default": "pg", "blocking": True,
            }),
        ])

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
        mock_ws_cls.return_value = _preload_ws_server([
            _output_msg("done"),
            _status_msg("exited", 0),
        ])

        state = {"worker_input": _valid_worker_input()}
        docker_worker_handler(state)
        get_archive_calls = [
            c for c in mock_container.get_archive.call_args_list
            if "progress.jsonl" in str(c)
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

        state = {"worker_input": _valid_worker_input()}
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


class TestICRNLFix:
    """Tests for ICRNL: handler sends \\n in InputMessage (adapter converts to \\r)."""

    @patch("archipelago.docker_worker.handler.TRUST_RETRY_INTERVAL", 0.3)
    @patch("archipelago.docker_worker.handler.TRUST_FLUSH_DELAY", 0.1)
    @patch("archipelago.docker_worker.handler.TRUST_POLL_INTERVAL", 0.05)
    @patch("archipelago.docker_worker.handler.TRUST_TIMEOUT", 2.0)
    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_trust_prompt_when_confirmed_then_sends_newline_not_carriage_return(
        self, mock_docker, mock_ws_cls
    ):
        """Trust confirmation sends \\n in InputMessage; adapter handles \\r conversion."""
        _mock_docker_env(mock_docker)

        ws_server = _preload_ws_server([])
        mock_ws_cls.return_value = ws_server

        # Pre-load output then exited status after a delay
        def _delayed_messages():
            import time
            time.sleep(0.5)
            ws_server.message_queue.put(_output_msg("trust prompt line"))
            time.sleep(1.0)
            ws_server.message_queue.put(_output_msg("trust accepted"))
            time.sleep(1.0)
            ws_server.message_queue.put(_status_msg("exited", 0))

        feeder = threading.Thread(target=_delayed_messages, daemon=True)
        feeder.start()

        state = {"worker_input": _valid_worker_input()}
        docker_worker_handler(state)

        # Check send calls for InputMessage with \n (not \r)
        send_calls = ws_server.send.call_args_list
        input_calls = []
        for c in send_calls:
            try:
                msg = json.loads(c[0][0])
                if msg.get("type") == "input":
                    input_calls.append(msg)
            except (json.JSONDecodeError, IndexError):
                pass

        # Trust calls should have \n
        trust_calls = [m for m in input_calls if m["text"] == "\n"]
        assert len(trust_calls) >= 1, f"Expected trust \\n calls, got: {input_calls}"

        # No \r calls should exist
        cr_calls = [m for m in input_calls if m["text"] == "\r"]
        assert len(cr_calls) == 0, f"Found \\r calls (should be \\n): {cr_calls}"

    @patch("archipelago.docker_worker.handler.TRUST_RETRY_INTERVAL", 0.3)
    @patch("archipelago.docker_worker.handler.TRUST_FLUSH_DELAY", 0.1)
    @patch("archipelago.docker_worker.handler.TRUST_POLL_INTERVAL", 0.05)
    @patch("archipelago.docker_worker.handler.TRUST_TIMEOUT", 2.0)
    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_feature_prompt_when_sent_then_ends_with_newline(
        self, mock_docker, mock_ws_cls
    ):
        """Feature prompt ends with \\n in InputMessage."""
        _mock_docker_env(mock_docker)

        ws_server = _preload_ws_server([])
        mock_ws_cls.return_value = ws_server

        def _delayed_messages():
            import time
            time.sleep(0.5)
            ws_server.message_queue.put(_output_msg("trust prompt"))
            time.sleep(1.0)
            ws_server.message_queue.put(_output_msg("ready"))
            time.sleep(1.0)
            ws_server.message_queue.put(_status_msg("exited", 0))

        feeder = threading.Thread(target=_delayed_messages, daemon=True)
        feeder.start()

        state = {"worker_input": _valid_worker_input()}
        docker_worker_handler(state)

        send_calls = ws_server.send.call_args_list
        input_calls = []
        for c in send_calls:
            try:
                msg = json.loads(c[0][0])
                if msg.get("type") == "input":
                    input_calls.append(msg)
            except (json.JSONDecodeError, IndexError):
                pass

        prompt_calls = [m for m in input_calls if "Test" in m.get("text", "")]
        assert len(prompt_calls) == 1, f"Expected 1 prompt call, got: {input_calls}"
        assert prompt_calls[0]["text"].endswith("\n")

    def test_given_entrypoint_when_read_then_contains_stty_icrnl(self):
        """Entrypoint must disable ICRNL so \\r passes through PTY unchanged."""
        entrypoint = Path(__file__).parent.parent.parent / "docker" / "entrypoint.sh"
        content = entrypoint.read_text()
        assert "stty -icrnl" in content

    @patch("archipelago.docker_worker.handler.TRUST_RETRY_INTERVAL", 0.3)
    @patch("archipelago.docker_worker.handler.TRUST_FLUSH_DELAY", 0.1)
    @patch("archipelago.docker_worker.handler.TRUST_POLL_INTERVAL", 0.05)
    @patch("archipelago.docker_worker.handler.TRUST_TIMEOUT", 2.0)
    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_slow_cc_startup_when_trust_prompt_delayed_then_retry_loop_sends_multiple_inputs(
        self, mock_docker, mock_ws_cls
    ):
        """When CC takes several seconds to render trust prompt, handler retries \\n."""
        _mock_docker_env(mock_docker)

        ws_server = _preload_ws_server([])
        mock_ws_cls.return_value = ws_server

        def _delayed_messages():
            import time
            time.sleep(0.3)
            ws_server.message_queue.put(_output_msg("version check"))
            time.sleep(1.5)
            ws_server.message_queue.put(_output_msg("trust accepted"))
            time.sleep(1.0)
            ws_server.message_queue.put(_status_msg("exited", 0))

        feeder = threading.Thread(target=_delayed_messages, daemon=True)
        feeder.start()

        state = {"worker_input": _valid_worker_input()}
        docker_worker_handler(state)

        send_calls = ws_server.send.call_args_list
        input_calls = []
        for c in send_calls:
            try:
                msg = json.loads(c[0][0])
                if msg.get("type") == "input" and msg["text"] == "\n":
                    input_calls.append(msg)
            except (json.JSONDecodeError, IndexError):
                pass

        assert len(input_calls) >= 2, f"Expected multiple \\n retries, got {len(input_calls)}"

    @patch("archipelago.docker_worker.handler.TRUST_TIMEOUT", 1.0)
    @patch("archipelago.docker_worker.handler.TRUST_RETRY_INTERVAL", 0.3)
    @patch("archipelago.docker_worker.handler.TRUST_FLUSH_DELAY", 0.1)
    @patch("archipelago.docker_worker.handler.TRUST_POLL_INTERVAL", 0.05)
    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_trust_timeout_when_cc_never_starts_then_prompt_still_sent(
        self, mock_docker, mock_ws_cls
    ):
        """When trust loop times out, the prompt is still sent (graceful degradation)."""
        _mock_docker_env(mock_docker)

        ws_server = _preload_ws_server([])
        mock_ws_cls.return_value = ws_server

        def _delayed_messages():
            import time
            time.sleep(0.3)
            ws_server.message_queue.put(_output_msg("version check"))
            time.sleep(3)
            ws_server.message_queue.put(_status_msg("exited", 0))

        feeder = threading.Thread(target=_delayed_messages, daemon=True)
        feeder.start()

        state = {"worker_input": _valid_worker_input()}
        docker_worker_handler(state)

        send_calls = ws_server.send.call_args_list
        input_calls = []
        for c in send_calls:
            try:
                msg = json.loads(c[0][0])
                if msg.get("type") == "input":
                    input_calls.append(msg)
            except (json.JSONDecodeError, IndexError):
                pass

        prompt_calls = [m for m in input_calls if "Test" in m.get("text", "")]
        assert len(prompt_calls) == 1, f"Expected prompt sent after timeout, got: {input_calls}"


class TestHandlerProtocol:
    """Tests for WebSocket protocol message handling in the handler."""

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_adapter_sends_output_when_handler_running_then_output_collected(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server([
            _output_msg("line 1"),
            _output_msg("line 2"),
            _status_msg("exited", 0),
        ])

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        assert "2 output lines" in result["worker_result"]["result_summary"]

    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_adapter_sends_clarification_interrupt_when_handler_running_then_breakpoint_set(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        mock_ws_cls.return_value = _preload_ws_server([
            _interrupt_msg("clarification", {
                "question": "Which DB?", "options": ["pg"],
                "default": "pg", "blocking": True,
            }),
        ])

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
        ws_server = _preload_ws_server([
            _interrupt_msg("permission", {
                "action": "delete file", "risk_level": "low",
                "why_needed": "cleanup",
            }),
            _status_msg("exited", 0),
        ])
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
        mock_ws_cls.return_value = _preload_ws_server([
            _interrupt_msg("update_available", {
                "installed": "1.0.0", "latest": "1.1.0",
            }),
            _status_msg("exited", 0),
        ])

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
        mock_ws_cls.return_value = _preload_ws_server([
            _output_msg("done"),
            _status_msg("exited", 0),
        ])

        state = {"worker_input": _valid_worker_input()}
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

    @patch("archipelago.docker_worker.handler.TRUST_RETRY_INTERVAL", 0.3)
    @patch("archipelago.docker_worker.handler.TRUST_FLUSH_DELAY", 0.1)
    @patch("archipelago.docker_worker.handler.TRUST_POLL_INTERVAL", 0.05)
    @patch("archipelago.docker_worker.handler.TRUST_TIMEOUT", 2.0)
    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_handler_needs_trust_confirmation_when_connected_then_sends_input_messages(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        ws_server = _preload_ws_server([])
        mock_ws_cls.return_value = ws_server

        def _delayed_messages():
            import time
            time.sleep(0.3)
            ws_server.message_queue.put(_output_msg("first output"))
            time.sleep(1.0)
            ws_server.message_queue.put(_output_msg("trust accepted"))
            time.sleep(1.0)
            ws_server.message_queue.put(_status_msg("exited", 0))

        feeder = threading.Thread(target=_delayed_messages, daemon=True)
        feeder.start()

        state = {"worker_input": _valid_worker_input()}
        docker_worker_handler(state)

        send_calls = ws_server.send.call_args_list
        input_calls = []
        for c in send_calls:
            try:
                msg = json.loads(c[0][0])
                if msg.get("type") == "input":
                    input_calls.append(msg)
            except (json.JSONDecodeError, IndexError):
                pass
        assert len(input_calls) >= 1

    @patch("archipelago.docker_worker.handler.TRUST_RETRY_INTERVAL", 0.3)
    @patch("archipelago.docker_worker.handler.TRUST_FLUSH_DELAY", 0.1)
    @patch("archipelago.docker_worker.handler.TRUST_POLL_INTERVAL", 0.05)
    @patch("archipelago.docker_worker.handler.TRUST_TIMEOUT", 2.0)
    @patch("archipelago.docker_worker.handler._HandlerWSServer")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_handler_needs_prompt_delivery_when_connected_then_sends_input_message(
        self, mock_docker, mock_ws_cls
    ):
        _mock_docker_env(mock_docker)
        ws_server = _preload_ws_server([])
        mock_ws_cls.return_value = ws_server

        def _delayed_messages():
            import time
            time.sleep(0.3)
            ws_server.message_queue.put(_output_msg("first output"))
            time.sleep(1.0)
            ws_server.message_queue.put(_output_msg("ready"))
            time.sleep(1.0)
            ws_server.message_queue.put(_status_msg("exited", 0))

        feeder = threading.Thread(target=_delayed_messages, daemon=True)
        feeder.start()

        state = {"worker_input": _valid_worker_input()}
        docker_worker_handler(state)

        send_calls = ws_server.send.call_args_list
        input_calls = []
        for c in send_calls:
            try:
                msg = json.loads(c[0][0])
                if msg.get("type") == "input" and "Test" in msg.get("text", ""):
                    input_calls.append(msg)
            except (json.JSONDecodeError, IndexError):
                pass
        assert len(input_calls) == 1
        assert "Implement the following feature:" in input_calls[0]["text"]


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
