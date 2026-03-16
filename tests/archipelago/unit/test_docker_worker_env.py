"""Unit tests for Archipelago container environment variable builder."""

from archipelago.docker_worker.env import build_container_env
from archipelago.docker_worker.models import WorkerConstraints, WorkerInput


def _make_worker_input(**overrides) -> WorkerInput:
    defaults = {
        "repo_ref": "main",
        "feature_spec": {"title": "test"},
        "constraints": WorkerConstraints(),
        "test_commands": ["pdm run pytest"],
    }
    defaults.update(overrides)
    return WorkerInput(**defaults)


class TestBuildContainerEnv:
    def test_given_worker_input_when_built_then_contains_ws_url(self):
        env = build_container_env(_make_worker_input(), ws_url="ws://host:1234/abc")
        assert env["ARCHIPELAGO_WS_URL"] == "ws://host:1234/abc"

    def test_given_worker_input_when_built_then_contains_turn_timeout(self):
        wi = _make_worker_input(constraints=WorkerConstraints(turn_timeout_seconds=600))
        env = build_container_env(wi, ws_url="ws://host:1234/abc")
        assert env["ARCHIPELAGO_TURN_TIMEOUT"] == "600"

    def test_given_skip_permissions_true_when_built_then_skip_is_1(self):
        wi = _make_worker_input(constraints=WorkerConstraints(skip_permissions=True))
        env = build_container_env(wi, ws_url="ws://host:1234/abc")
        assert env["ARCHIPELAGO_SKIP_PERMISSIONS"] == "1"

    def test_given_skip_permissions_false_when_built_then_skip_is_0(self):
        wi = _make_worker_input(constraints=WorkerConstraints(skip_permissions=False))
        env = build_container_env(wi, ws_url="ws://host:1234/abc")
        assert env["ARCHIPELAGO_SKIP_PERMISSIONS"] == "0"

    def test_given_repo_url_without_workspace_volume_when_built_then_contains_repo_url(self):
        wi = _make_worker_input(repo_url="https://github.com/org/repo")
        env = build_container_env(wi, ws_url="ws://host:1234/abc")
        assert env["REPO_URL"] == "https://github.com/org/repo"

    def test_given_repo_url_with_workspace_volume_when_built_then_no_repo_url(self):
        wi = _make_worker_input(
            repo_url="https://github.com/org/repo",
            workspace_volume="existing-vol",
        )
        env = build_container_env(wi, ws_url="ws://host:1234/abc")
        assert "REPO_URL" not in env

    def test_given_hidden_dirs_when_built_then_delegates_to_build_lockdown_env(self):
        wi = _make_worker_input(acp_hidden_dirs=["/workspace/src"])
        env = build_container_env(wi, ws_url="ws://host:1234/abc")
        assert env["ACP_HIDDEN_DIRS"] == "/workspace/src"

    def test_given_no_lockdown_config_when_built_then_no_lockdown_keys(self):
        env = build_container_env(_make_worker_input(), ws_url="ws://host:1234/abc")
        assert "ACP_HIDDEN_DIRS" not in env
        assert "ACP_READONLY_DIRS" not in env
        assert "ACP_ROLE_INSTRUCTIONS_PATH" not in env
