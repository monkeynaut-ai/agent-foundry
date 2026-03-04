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
        mock_client, _mock_container = _mock_docker_env(mock_docker)

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
