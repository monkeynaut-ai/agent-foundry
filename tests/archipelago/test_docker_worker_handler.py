"""Docker worker handler — unit tests with mocked Docker and pipeline integration."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.planner.validators import validate_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import CapabilityRegistry
from archipelago.docker_worker.handler import DOCKER_WORKER_HANDLERS, docker_worker_handler
from archipelago.docker_worker.models import WorkerConstraints

PRODUCT_CAPS_DIR = Path(__file__).parent.parent.parent / "src" / "archipelago" / "capabilities"
PLAN_PATH = Path(__file__).parent.parent.parent / "src" / "archipelago" / "pipeline_plan.json"


@pytest.fixture
def registry():
    return CapabilityRegistry.with_product_specs(PRODUCT_CAPS_DIR)


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


class TestDockerWorkerHandler:
    @patch("archipelago.docker_worker.handler.docker")
    def test_given_valid_worker_input_when_called_then_container_created_and_started(
        self, mock_docker
    ):
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.id = "c1"
        mock_client.containers.create.return_value = mock_container
        mock_container.client.api.exec_create.return_value = {"Id": "e1"}
        mock_container.client.api.exec_start.return_value = iter([])
        mock_docker.from_env.return_value = mock_client

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        mock_client.containers.create.assert_called_once()
        assert "worker_result" in result

    @patch("archipelago.docker_worker.handler.docker")
    def test_given_valid_worker_input_when_called_then_session_launched(
        self, mock_docker
    ):
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.id = "c1"
        mock_client.containers.create.return_value = mock_container
        mock_container.client.api.exec_create.return_value = {"Id": "e1"}
        mock_container.client.api.exec_start.return_value = iter([])
        mock_docker.from_env.return_value = mock_client

        state = {"worker_input": _valid_worker_input()}
        docker_worker_handler(state)
        mock_container.client.api.exec_create.assert_called_once()

    @patch("archipelago.docker_worker.handler.docker")
    def test_given_successful_cc_run_when_called_then_worker_result_returned(
        self, mock_docker
    ):
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.id = "c1"
        mock_client.containers.create.return_value = mock_container
        mock_container.client.api.exec_create.return_value = {"Id": "e1"}
        mock_container.client.api.exec_start.return_value = iter([b"done\n"])
        mock_docker.from_env.return_value = mock_client

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        assert result["worker_result"] is not None
        assert result["worker_result"]["status"] in ("completed", "failed")

    @patch("archipelago.docker_worker.handler.docker")
    def test_given_docker_unavailable_when_called_then_status_is_failed(
        self, mock_docker
    ):
        mock_docker.from_env.side_effect = Exception("Docker not running")

        state = {"worker_input": _valid_worker_input()}
        result = docker_worker_handler(state)
        assert result["worker_result"]["status"] == "failed"
        assert "Docker unavailable" in result["worker_result"]["result_summary"]

    @patch("archipelago.docker_worker.handler.docker")
    def test_given_handler_completes_when_called_then_container_destroyed(
        self, mock_docker
    ):
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.id = "c1"
        mock_client.containers.create.return_value = mock_container
        mock_container.client.api.exec_create.return_value = {"Id": "e1"}
        mock_container.client.api.exec_start.return_value = iter([])
        mock_docker.from_env.return_value = mock_client

        state = {"worker_input": _valid_worker_input()}
        docker_worker_handler(state)
        mock_container.remove.assert_called_once()


class TestPipelineIntegration:
    def test_given_updated_plan_when_validated_then_all_7_checks_pass(
        self, plan, registry
    ):
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
