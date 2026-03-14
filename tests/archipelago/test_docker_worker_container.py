"""Docker worker container lifecycle — unit tests with mocked Docker SDK."""

import io
import tarfile
from unittest.mock import MagicMock

import pytest

from archipelago.docker_worker.container import (
    ContainerHandle,
    ContainerManager,
    DEFAULT_ENV_ALLOWLIST,
)
from archipelago.docker_worker.errors import ContainerCreationError
from archipelago.docker_worker.models import WorkerConstraints


@pytest.fixture
def mock_client():
    client = MagicMock()
    mock_container = MagicMock()
    mock_container.id = "container-abc123"
    # Default exec_run returns success (exit_code=0) for image validation
    mock_container.exec_run.return_value = (0, b"/home/claude/.local/bin/claude")
    client.containers.create.return_value = mock_container
    return client


@pytest.fixture
def manager(mock_client):
    return ContainerManager(mock_client, default_image="archipelago-cc-worker:latest")


# ── Commit 1: create_container with safety baseline ──


class TestCreateContainer:
    def test_given_valid_config_when_create_called_then_returns_container_handle(self, manager):
        handle = manager.create_container(workspace_volume="vol-1")
        assert isinstance(handle, ContainerHandle)
        assert handle.container_id == "container-abc123"
        assert handle.status == "created"

    def test_given_valid_config_when_create_called_then_no_entrypoint_override(
        self, manager, mock_client
    ):
        manager.create_container()
        call_kwargs = mock_client.containers.create.call_args
        assert "entrypoint" not in call_kwargs.kwargs
        assert "command" not in call_kwargs.kwargs

    def test_given_valid_config_when_create_called_then_extra_hosts_set(self, manager, mock_client):
        manager.create_container()
        call_kwargs = mock_client.containers.create.call_args
        assert call_kwargs.kwargs["extra_hosts"] == {"host.docker.internal": "host-gateway"}

    def test_given_valid_config_when_create_called_then_container_uses_non_root_user(
        self, manager, mock_client
    ):
        manager.create_container()
        call_kwargs = mock_client.containers.create.call_args
        assert call_kwargs.kwargs["user"] == "1000:1000"

    def test_given_valid_config_when_create_called_then_all_capabilities_dropped(
        self, manager, mock_client
    ):
        manager.create_container()
        call_kwargs = mock_client.containers.create.call_args
        assert call_kwargs.kwargs["cap_drop"] == ["ALL"]

    def test_given_valid_config_when_create_called_then_rootfs_is_writable(
        self, manager, mock_client
    ):
        manager.create_container()
        call_kwargs = mock_client.containers.create.call_args
        assert call_kwargs.kwargs["read_only"] is False

    def test_given_resource_limits_when_create_called_then_limits_applied(
        self, manager, mock_client
    ):
        constraints = WorkerConstraints(mem_limit_mb=1024, cpu_quota=50000, pids_limit=100)
        manager.create_container(constraints=constraints)
        call_kwargs = mock_client.containers.create.call_args
        assert call_kwargs.kwargs["tmpfs"] == {"/tmp": "size=256m"}
        assert call_kwargs.kwargs["mem_limit"] == "1024m"
        assert call_kwargs.kwargs["cpu_quota"] == 50000
        assert call_kwargs.kwargs["pids_limit"] == 100

    def test_given_default_constraints_when_create_called_then_mem_limit_applied(
        self, manager, mock_client
    ):
        constraints = WorkerConstraints()
        manager.create_container(constraints=constraints)
        call_kwargs = mock_client.containers.create.call_args
        assert call_kwargs.kwargs["mem_limit"] == "512m"

    def test_given_env_vars_when_create_called_then_only_allowlisted_vars_passed(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("HOME", "/home")
        monkeypatch.setenv("SECRET", "hidden")

        client = MagicMock()
        mock_container = MagicMock()
        mock_container.id = "c1"
        client.containers.create.return_value = mock_container

        mgr = ContainerManager(client, default_image="test:latest", env_allowlist={"PATH", "HOME"})
        mgr.create_container()

        call_kwargs = client.containers.create.call_args
        env = call_kwargs.kwargs["environment"]
        assert "PATH" in env
        assert "HOME" in env
        assert "SECRET" not in env

    def test_given_extra_env_when_create_called_then_extra_env_merged(self, manager, mock_client):
        manager.create_container(extra_env={"ARCHIPELAGO_WS_URL": "ws://host:1234/abc"})
        call_kwargs = mock_client.containers.create.call_args
        env = call_kwargs.kwargs["environment"]
        assert env["ARCHIPELAGO_WS_URL"] == "ws://host:1234/abc"

    def test_given_github_token_on_host_when_create_called_then_token_forwarded_to_container(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_testtoken123")

        client = MagicMock()
        mock_container = MagicMock()
        mock_container.id = "c1"
        client.containers.create.return_value = mock_container

        mgr = ContainerManager(
            client,
            default_image="archipelago-cc-worker:latest",
            env_allowlist=DEFAULT_ENV_ALLOWLIST,
        )
        mgr.create_container()

        call_kwargs = client.containers.create.call_args
        env = call_kwargs.kwargs["environment"]
        assert env["GITHUB_TOKEN"] == "ghp_testtoken123"

    def test_given_ws_url_env_var_when_create_called_then_ws_url_forwarded_to_container(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("ARCHIPELAGO_WS_URL", "ws://host:5678/session")

        client = MagicMock()
        mock_container = MagicMock()
        mock_container.id = "c1"
        client.containers.create.return_value = mock_container

        mgr = ContainerManager(
            client,
            default_image="archipelago-cc-worker:latest",
            env_allowlist=DEFAULT_ENV_ALLOWLIST,
        )
        mgr.create_container()

        call_kwargs = client.containers.create.call_args
        env = call_kwargs.kwargs["environment"]
        assert env["ARCHIPELAGO_WS_URL"] == "ws://host:5678/session"


# ── Commit 2: start, stop, destroy ──


class TestStartContainer:
    def test_given_created_container_when_start_called_then_status_becomes_running(self, manager):
        handle = manager.create_container()
        manager.start(handle)
        assert handle.status == "running"

    def test_given_started_container_when_start_called_then_no_git_clone_exec_run(self, manager):
        handle = manager.create_container()
        manager.start(handle)
        handle._container.exec_run.assert_not_called()

    def test_given_image_without_cc_when_validate_called_then_raises_with_actionable_message(
        self, manager
    ):
        handle = manager.create_container()
        # Mock exec_run to simulate 'which claude' failing (exit code 1)
        handle._container.exec_run.return_value = (1, b"")
        with pytest.raises(ContainerCreationError, match="claude"):
            manager.validate_image(handle)

    def test_given_image_with_cc_when_start_called_then_no_validation_error(self, manager):
        handle = manager.create_container()
        manager.start(handle)
        assert handle.status == "running"


class TestStopContainer:
    def test_given_running_container_when_stop_called_then_status_becomes_stopped(self, manager):
        handle = manager.create_container()
        manager.start(handle)
        manager.stop(handle)
        assert handle.status == "stopped"

    def test_given_running_container_when_stop_called_then_graceful_shutdown_attempted(
        self, manager
    ):
        handle = manager.create_container()
        manager.start(handle)
        manager.stop(handle, timeout=15)
        handle._container.stop.assert_called_once_with(timeout=15)


class TestDestroyContainer:
    def test_given_stopped_container_when_destroy_called_then_container_removed(self, manager):
        handle = manager.create_container()
        manager.start(handle)
        manager.stop(handle)
        manager.destroy(handle)
        handle._container.remove.assert_called_once()
        assert handle.status == "destroyed"

    def test_given_stopped_container_when_destroy_called_then_volumes_never_removed(self, manager):
        handle = manager.create_container()
        manager.stop(handle)
        manager.destroy(handle)
        handle._container.remove.assert_called_once_with(v=False)


# ── Commit 4a: cleanup_all ──


class TestCleanupAll:
    def _make_multi_container_manager(self):
        """Create a manager that returns distinct mock containers."""
        client = MagicMock()
        containers = []

        def _create_side_effect(*args, **kwargs):
            c = MagicMock()
            c.id = f"container-{len(containers)}"
            c.exec_run.return_value = (0, b"/usr/bin/claude")
            containers.append(c)
            return c

        client.containers.create.side_effect = _create_side_effect
        return ContainerManager(client, default_image="archipelago-cc-worker:latest")

    def test_given_two_created_containers_when_cleanup_all_called_then_both_removed(self):
        manager = self._make_multi_container_manager()
        h1 = manager.create_container()
        h2 = manager.create_container()
        manager.cleanup_all()
        h1._container.remove.assert_called_once()
        h2._container.remove.assert_called_once()
        assert h1.status == "destroyed"
        assert h2.status == "destroyed"

    def test_given_one_destroyed_and_one_running_when_cleanup_all_called_then_only_running_cleaned(
        self,
    ):
        manager = self._make_multi_container_manager()
        h1 = manager.create_container()
        h2 = manager.create_container()
        manager.destroy(h1)
        h1._container.remove.reset_mock()

        manager.cleanup_all()
        # h1 was already destroyed, so remove should NOT be called again
        h1._container.remove.assert_not_called()
        h2._container.remove.assert_called_once()


# ── Commit 4b: validate_image (isolated) ──


class TestValidateImage:
    def test_given_container_with_claude_available_then_no_error(self, manager):
        handle = manager.create_container()
        handle._container.exec_run.return_value = (0, b"/usr/local/bin/claude")
        manager.validate_image(handle)  # Should not raise

    def test_given_container_missing_claude_then_raises_with_actionable_message(self, manager):
        handle = manager.create_container()
        handle._container.exec_run.return_value = (1, b"")
        with pytest.raises(ContainerCreationError, match="claude"):
            manager.validate_image(handle)


def _make_tar_bytes(filename: str, content: str) -> bytes:
    """Helper: create an in-memory tar archive containing a single file."""
    buf = io.BytesIO()
    data = content.encode()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name=filename)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestContainerFileIO:
    def test_given_running_container_when_read_file_then_contents_returned(self, manager):
        handle = manager.create_container()
        tar_bytes = _make_tar_bytes("progress.jsonl", '{"type":"ok"}\n')
        handle._container.get_archive.return_value = (iter([tar_bytes]), {"size": len(tar_bytes)})

        result = manager.read_file_from_container(handle, "/workspace/progress.jsonl")
        assert result == '{"type":"ok"}\n'
        handle._container.get_archive.assert_called_once_with("/workspace/progress.jsonl")

    def test_given_running_container_when_read_nonexistent_file_then_returns_none(self, manager):
        handle = manager.create_container()
        from docker.errors import NotFound

        handle._container.get_archive.side_effect = NotFound("not found")

        result = manager.read_file_from_container(handle, "/workspace/missing.txt")
        assert result is None

    def test_given_running_container_when_copy_from_container_then_file_written_to_host(
        self, manager, tmp_path
    ):
        handle = manager.create_container()
        tar_bytes = _make_tar_bytes("progress.jsonl", "line1\nline2\n")
        handle._container.get_archive.return_value = (iter([tar_bytes]), {"size": len(tar_bytes)})

        dest = tmp_path / "progress.jsonl"
        result = manager.copy_from_container(handle, "/workspace/progress.jsonl", dest)
        assert result is True
        assert dest.read_text() == "line1\nline2\n"

    def test_given_running_container_when_write_file_to_container_then_put_archive_called(
        self, manager
    ):
        handle = manager.create_container()
        manager.write_file_to_container(handle, "/workspace/spec.json", '{"title":"x"}')
        handle._container.put_archive.assert_called_once()
        call_args = handle._container.put_archive.call_args
        assert call_args.args[0] == "/workspace"
