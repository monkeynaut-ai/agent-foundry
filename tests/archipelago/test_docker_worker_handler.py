"""Docker worker handler — unit tests with mocked Docker and pipeline integration."""

import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.planner.validators import validate_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from archipelago.docker_worker.handler import docker_worker_handler
from archipelago.docker_worker.models import WorkerConstraints, WorkerResult

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

    def __init__(self, mock_docker, stream=None):
        self.client = MagicMock()
        self.container = MagicMock()
        self.container.id = "c1"
        self.container.exec_run.return_value = (0, b"/home/claude/.local/bin/claude")
        self.client.containers.create.return_value = self.container
        self.container.client.api.exec_create.return_value = {"Id": "e1"}
        self.container.client.api.exec_start.return_value = (
            stream if stream is not None else iter([])
        )
        mock_docker.from_env.return_value = self.client

    @property
    def exec_api(self):
        return self.container.client.api


def _mock_docker_env(mock_docker, stream=None):
    """Create a standard mock Docker client/container for handler tests."""
    helper = DockerTestHelper(mock_docker, stream)
    return helper.client, helper.container


class TestDockerWorkerHandler:
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_valid_worker_input_when_called_then_container_created_and_started(
        self, mock_docker
    ):
        mock_client, _ = _mock_docker_env(mock_docker)

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        mock_client.containers.create.assert_called_once()
        assert "worker_result" in result

    @patch("archipelago.docker_worker.handler.docker")
    def test_given_valid_worker_input_when_called_then_session_launched(self, mock_docker):
        _, mock_container = _mock_docker_env(mock_docker)

        state = {"worker_input": _valid_worker_input()}
        docker_worker_handler(state)
        mock_container.client.api.exec_create.assert_called_once()

    @patch("archipelago.docker_worker.handler.docker")
    def test_given_successful_cc_run_when_called_then_worker_result_returned(self, mock_docker):
        _mock_docker_env(mock_docker, stream=iter([b"done\n"]))

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

    @patch("archipelago.docker_worker.handler.docker")
    def test_given_handler_completes_when_called_then_container_destroyed(self, mock_docker):
        _, mock_container = _mock_docker_env(mock_docker)

        state = {"worker_input": _valid_worker_input()}
        docker_worker_handler(state)
        mock_container.remove.assert_called_once()

    @patch("archipelago.docker_worker.handler.docker")
    def test_given_successful_cc_run_when_called_then_worker_result_validates(self, mock_docker):
        _mock_docker_env(mock_docker, stream=iter([b"done\n"]))

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        worker_result = WorkerResult(**result["worker_result"])
        assert worker_result.status in ("completed", "failed")
        assert isinstance(worker_result.patches, list)
        assert isinstance(worker_result.evidence, list)

    @patch("archipelago.docker_worker.handler.docker")
    def test_given_cc_timeout_when_called_then_status_is_timed_out(self, mock_docker):
        block = threading.Event()

        def _slow_stream():
            yield b"working...\n"
            block.wait(timeout=10)

        _mock_docker_env(mock_docker, stream=_slow_stream())

        worker_input = _valid_worker_input()
        worker_input["constraints"]["timeout_seconds"] = 0
        state = {"worker_input": worker_input}
        result = docker_worker_handler(state)
        block.set()  # unblock the generator so the thread can exit
        assert result["worker_result"]["status"] == "timed_out"

    @patch("archipelago.docker_worker.handler.docker")
    def test_given_interrupt_during_run_when_called_then_breakpoint_payload_set(self, mock_docker):
        block = threading.Event()

        def _interrupt_stream():
            yield b'ARCHIPELAGO_NEED_CLARIFICATION {"question": "Which DB?", "options": ["pg"], "default": "pg", "blocking": true}\n'
            block.wait(timeout=10)

        _mock_docker_env(mock_docker, stream=_interrupt_stream())

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        block.set()  # unblock the generator so the thread can exit
        assert result.get("breakpoint_payload") is not None
        assert result["breakpoint_payload"]["type"] == "clarification"
        assert result["worker_result"] is None


    @patch("archipelago.docker_worker.handler.docker")
    def test_given_successful_cc_run_when_called_then_progress_read_from_container(
        self, mock_docker
    ):
        _, mock_container = _mock_docker_env(mock_docker, stream=iter([b"done\n"]))

        state = {"worker_input": _valid_worker_input()}
        docker_worker_handler(state)
        # Verify get_archive was called to read progress from inside container
        get_archive_calls = [
            c for c in mock_container.get_archive.call_args_list
            if "progress.jsonl" in str(c)
        ]
        assert len(get_archive_calls) > 0

    @patch("archipelago.docker_worker.handler.persist_workspace_state")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_cc_crash_when_called_then_workspace_state_persisted(
        self, mock_docker, mock_persist
    ):
        _, mock_container = _mock_docker_env(mock_docker)
        # Make session launch raise to simulate CC crash
        mock_container.client.api.exec_create.side_effect = RuntimeError("CC crashed")

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)

        assert result["worker_result"]["status"] == "failed"
        mock_persist.assert_called_once()


    @patch("archipelago.docker_worker.handler.docker")
    def test_given_no_worker_input_when_state_has_feature_spec_then_worker_input_constructed(
        self, mock_docker
    ):
        """Fallback path: construct WorkerInput from individual state keys."""
        mock_client, _ = _mock_docker_env(mock_docker)

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

    @patch("archipelago.docker_worker.handler.docker")
    def test_given_no_worker_input_when_defaults_used_then_worker_input_constructed(
        self, mock_docker
    ):
        """Fallback path with minimal state — defaults fill in."""
        _mock_docker_env(mock_docker)

        state = {"feature_spec": {"title": "Minimal"}}
        result = docker_worker_handler(state)
        assert "worker_result" in result

    @patch("archipelago.docker_worker.handler.SessionManager")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_valid_state_when_session_launched_then_prompt_sent_after_trust(
        self, mock_docker, mock_session_cls
    ):
        """After trust confirmation, the feature spec prompt is sent to stdin."""
        _mock_docker_env(mock_docker)

        mock_session_mgr = MagicMock()
        mock_session_cls.return_value = mock_session_mgr
        mock_session = MagicMock()
        mock_session.status = "exited"
        mock_session.exit_code = 0
        mock_session_mgr.launch_session.return_value = mock_session

        # Capture the output callback so we can trigger first_output
        captured_callbacks = []
        mock_session_mgr.register_output_callback.side_effect = lambda cb: captured_callbacks.append(cb)

        state = {"worker_input": _valid_worker_input()}

        # Run handler in a thread so we can trigger the callback
        import time

        result_holder = []
        def _run():
            result_holder.append(docker_worker_handler(state))

        t = threading.Thread(target=_run)
        t.start()

        # Give handler time to set up, then simulate CC output to trigger first_output
        time.sleep(0.5)
        for cb in captured_callbacks:
            cb("trust prompt line", "c1", 0.0)
        # Simulate second output line (trust accepted) to trigger prompt send
        time.sleep(1.5)
        for cb in captured_callbacks:
            cb("trust accepted", "c1", 0.0)

        # Wait for prompt thread to complete
        time.sleep(2)
        t.join(timeout=5)

        calls = mock_session_mgr.send_input.call_args_list
        # First call: trust confirmation (\r), second: the feature spec prompt ending with \r
        assert len(calls) >= 2, f"Expected at least 2 send_input calls, got {len(calls)}: {calls}"
        assert calls[0][0][1] == "\r"
        assert "Test" in calls[1][0][1]  # feature_spec title appears in prompt
        assert calls[1][0][1].endswith("\r")  # prompt ends with \r for PTY submit


class TestICRNLFix:
    """Tests for the ICRNL fix: handler sends \\r instead of \\n for PTY submit."""

    @patch("archipelago.docker_worker.handler.SessionManager")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_trust_prompt_when_confirmed_then_sends_carriage_return_not_newline(
        self, mock_docker, mock_session_cls
    ):
        """Trust confirmation must send \\r so Ink's parse-keypress sees 'return'."""
        _mock_docker_env(mock_docker)

        mock_session_mgr = MagicMock()
        mock_session_cls.return_value = mock_session_mgr
        mock_session = MagicMock()
        mock_session.status = "exited"
        mock_session.exit_code = 0
        mock_session_mgr.launch_session.return_value = mock_session

        captured_callbacks = []
        mock_session_mgr.register_output_callback.side_effect = lambda cb: captured_callbacks.append(cb)

        state = {"worker_input": _valid_worker_input()}

        import time

        result_holder = []
        def _run():
            result_holder.append(docker_worker_handler(state))

        t = threading.Thread(target=_run)
        t.start()

        time.sleep(0.5)
        for cb in captured_callbacks:
            cb("trust prompt line", "c1", 0.0)
        time.sleep(1.5)
        for cb in captured_callbacks:
            cb("trust accepted", "c1", 0.0)

        time.sleep(2)
        t.join(timeout=5)

        calls = mock_session_mgr.send_input.call_args_list
        assert len(calls) >= 1
        # Trust confirmation must be \r, not \n
        trust_call = calls[0][0][1]
        assert trust_call == "\r", f"Expected '\\r' for trust confirm, got {trust_call!r}"
        assert "\n" not in trust_call

    @patch("archipelago.docker_worker.handler.SessionManager")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_feature_prompt_when_sent_then_ends_with_carriage_return(
        self, mock_docker, mock_session_cls
    ):
        """Feature prompt must end with \\r for PTY submit, not \\n."""
        _mock_docker_env(mock_docker)

        mock_session_mgr = MagicMock()
        mock_session_cls.return_value = mock_session_mgr
        mock_session = MagicMock()
        mock_session.status = "exited"
        mock_session.exit_code = 0
        mock_session_mgr.launch_session.return_value = mock_session

        captured_callbacks = []
        mock_session_mgr.register_output_callback.side_effect = lambda cb: captured_callbacks.append(cb)

        state = {"worker_input": _valid_worker_input()}

        import time

        result_holder = []
        def _run():
            result_holder.append(docker_worker_handler(state))

        t = threading.Thread(target=_run)
        t.start()

        time.sleep(0.5)
        for cb in captured_callbacks:
            cb("trust prompt line", "c1", 0.0)
        time.sleep(1.5)
        for cb in captured_callbacks:
            cb("trust accepted", "c1", 0.0)

        time.sleep(2)
        t.join(timeout=5)

        calls = mock_session_mgr.send_input.call_args_list
        assert len(calls) >= 2
        prompt_call = calls[1][0][1]
        assert prompt_call.endswith("\r"), f"Expected prompt to end with '\\r', got {prompt_call[-5:]!r}"
        assert not prompt_call.endswith("\n")

    @patch("archipelago.docker_worker.handler.sys")
    @patch("archipelago.docker_worker.handler.SessionManager")
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_stdin_line_when_forwarded_then_newline_replaced_with_carriage_return(
        self, mock_docker, mock_session_cls, mock_sys
    ):
        """Stdin forwarding must replace \\n with \\r so Ink treats it as submit."""
        _mock_docker_env(mock_docker)

        mock_session_mgr = MagicMock()
        mock_session_cls.return_value = mock_session_mgr
        mock_session = MagicMock()
        # Session runs briefly then exits
        call_count = 0
        def _status_getter():
            nonlocal call_count
            call_count += 1
            return "running" if call_count <= 20 else "exited"
        type(mock_session).status = property(lambda self: _status_getter())
        mock_session.exit_code = 0
        mock_session_mgr.launch_session.return_value = mock_session

        captured_callbacks = []
        mock_session_mgr.register_output_callback.side_effect = lambda cb: captured_callbacks.append(cb)

        # Simulate stdin providing one line then EOF
        mock_sys.stdin.readline.side_effect = ["hello world\n", ""]

        state = {"worker_input": _valid_worker_input()}

        import time

        result_holder = []
        def _run():
            result_holder.append(docker_worker_handler(state))

        t = threading.Thread(target=_run)
        t.start()

        # Trigger first_output to unblock trust thread
        time.sleep(0.5)
        for cb in captured_callbacks:
            cb("output line", "c1", 0.0)
        time.sleep(1.5)
        for cb in captured_callbacks:
            cb("ready", "c1", 0.0)

        time.sleep(3)
        t.join(timeout=5)

        # Find the stdin forwarding call (should contain "hello world")
        stdin_calls = [
            c for c in mock_session_mgr.send_input.call_args_list
            if "hello world" in str(c)
        ]
        assert len(stdin_calls) >= 1, f"Expected stdin forwarding call, got: {mock_session_mgr.send_input.call_args_list}"
        forwarded_text = stdin_calls[0][0][1]
        assert forwarded_text == "hello world\r", f"Expected 'hello world\\r', got {forwarded_text!r}"

    def test_given_entrypoint_when_read_then_contains_stty_icrnl(self):
        """Entrypoint must disable ICRNL so \\r passes through PTY unchanged."""
        entrypoint = Path(__file__).parent.parent.parent / "docker" / "entrypoint.sh"
        content = entrypoint.read_text()
        assert "stty -icrnl" in content, "entrypoint.sh must contain 'stty -icrnl'"


class TestPipelineIntegration:
    def test_given_updated_plan_when_validated_then_all_7_checks_pass(self, plan, registry):
        validate_plan(plan, registry)

    def test_given_handler_registry_with_docker_worker_when_compile_plan_called_then_compiles(
        self, plan, registry
    ):
        # Use stub handlers for the non-docker-worker nodes
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
