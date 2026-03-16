"""Integration tests: graph spec config → compiler → env builder → container lockdown.

Verifies the full pipeline from node config in a GraphWiringPlan through
compiler config injection, environment variable construction, and actual
filesystem lockdown enforcement in a real Docker container.

Requires: Docker daemon + acp-cc-worker:latest image (pdm docker-base).
"""

from typing import Any

import pytest

from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from archipelago.docker_worker.env import build_container_env
from archipelago.docker_worker.models import WorkerConstraints, WorkerInput
from tests.archipelago.integration.conftest import run_in_container


# ── Config → env builder pipeline (no Docker needed) ──


class TestConfigToEnvPipeline:
    """Compile a plan with lockdown config, verify env dict is correct."""

    def _compile_and_capture(self, config: dict[str, Any], registry) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        def spy(state):
            captured.update(state)
            return state

        plan = GraphWiringPlan(
            goal="test-config-to-env",
            nodes=[{"id": "worker", "role": "test_role", "config": config}],
            edges=[],
            entry_point="worker",
            role_versions={"test_role": "1.0.0"},
        )
        graph = compile_plan(plan, registry, handler_registry={"test_role": spy})
        graph.invoke({"input": "test"})
        return captured

    def test_given_plan_with_hidden_dirs_when_compiled_then_env_contains_acp_hidden_dirs(
        self, registry
    ):
        state = self._compile_and_capture({"acp_hidden_dirs": ["/workspace/secrets"]}, registry)
        worker_input = WorkerInput(
            repo_ref="main",
            feature_spec={},
            constraints=WorkerConstraints(),
            test_commands=[],
            acp_hidden_dirs=state["acp_hidden_dirs"],
        )
        env = build_container_env(worker_input, ws_url="ws://host:1234/test")
        assert env["ACP_HIDDEN_DIRS"] == "/workspace/secrets"

    def test_given_plan_with_readonly_dirs_when_compiled_then_env_contains_acp_readonly_dirs(
        self, registry
    ):
        state = self._compile_and_capture({"acp_readonly_dirs": ["/workspace/tests"]}, registry)
        worker_input = WorkerInput(
            repo_ref="main",
            feature_spec={},
            constraints=WorkerConstraints(),
            test_commands=[],
            acp_readonly_dirs=state["acp_readonly_dirs"],
        )
        env = build_container_env(worker_input, ws_url="ws://host:1234/test")
        assert env["ACP_READONLY_DIRS"] == "/workspace/tests"


# ── Env → container lockdown enforcement (Docker) ──


@pytest.mark.integration
class TestConfigToLockdownEnforcement:
    """Full pipeline: compile plan → build env → real container → lockdown works."""

    def test_given_compiled_hidden_dirs_env_when_container_runs_lockdown_then_dir_inaccessible(
        self, docker_client, worker_image, container_cleanup, registry
    ):
        # Step 1: Compile plan with hidden_dirs config
        captured: dict[str, Any] = {}

        def spy(state):
            captured.update(state)
            return state

        plan = GraphWiringPlan(
            goal="test-lockdown",
            nodes=[
                {
                    "id": "worker",
                    "role": "test_role",
                    "config": {"acp_hidden_dirs": ["/workspace/secrets"]},
                }
            ],
            edges=[],
            entry_point="worker",
            role_versions={"test_role": "1.0.0"},
        )
        graph = compile_plan(plan, registry, handler_registry={"test_role": spy})
        graph.invoke({})

        # Step 2: Build env from compiled state
        worker_input = WorkerInput(
            repo_ref="main",
            feature_spec={},
            constraints=WorkerConstraints(),
            test_commands=[],
            acp_hidden_dirs=captured["acp_hidden_dirs"],
        )
        env = build_container_env(worker_input, ws_url="ws://host:1234/test")

        # Step 3: Run real container with those env vars and verify lockdown
        script = """
            mkdir -p /workspace/secrets
            echo "secret-data" > /workspace/secrets/key.txt
            . /home/claude/lockdown.sh
            gosu claude sh -c 'cat /workspace/secrets/key.txt 2>&1'
        """
        exit_code, output = run_in_container(
            docker_client, worker_image, script, env=env, cleanup_list=container_cleanup
        )
        assert exit_code != 0
        assert "secret-data" not in output

    def test_given_compiled_readonly_dirs_env_when_container_runs_lockdown_then_dir_not_writable(
        self, docker_client, worker_image, container_cleanup, registry
    ):
        # Step 1: Compile plan with readonly_dirs config
        captured: dict[str, Any] = {}

        def spy(state):
            captured.update(state)
            return state

        plan = GraphWiringPlan(
            goal="test-lockdown",
            nodes=[
                {
                    "id": "worker",
                    "role": "test_role",
                    "config": {"acp_readonly_dirs": ["/workspace/config"]},
                }
            ],
            edges=[],
            entry_point="worker",
            role_versions={"test_role": "1.0.0"},
        )
        graph = compile_plan(plan, registry, handler_registry={"test_role": spy})
        graph.invoke({})

        # Step 2: Build env from compiled state
        worker_input = WorkerInput(
            repo_ref="main",
            feature_spec={},
            constraints=WorkerConstraints(),
            test_commands=[],
            acp_readonly_dirs=captured["acp_readonly_dirs"],
        )
        env = build_container_env(worker_input, ws_url="ws://host:1234/test")

        # Step 3: Run real container and verify readonly enforcement
        # Read should succeed, write should fail
        script = """
            mkdir -p /workspace/config
            echo "setting: true" > /workspace/config/app.yaml
            chown -R claude:claude /workspace/config
            . /home/claude/lockdown.sh
            gosu claude sh -c 'cat /workspace/config/app.yaml && echo READ_OK'
            gosu claude sh -c 'touch /workspace/config/new.txt 2>&1'
        """
        exit_code, output = run_in_container(
            docker_client, worker_image, script, env=env, cleanup_list=container_cleanup
        )
        assert "READ_OK" in output
        assert exit_code != 0
