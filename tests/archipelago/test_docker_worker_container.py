"""Docker worker container lifecycle — unit tests with mocked Docker SDK."""

from unittest.mock import MagicMock

import pytest

from archipelago.docker_worker.container import ContainerHandle, ContainerManager
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
    return ContainerManager(mock_client)


# ── Commit 1: create_container with safety baseline ──


class TestCreateContainer:
    def test_given_valid_config_when_create_called_then_returns_container_handle(self, manager):
        handle = manager.create_container(workspace_volume="vol-1")
        assert isinstance(handle, ContainerHandle)
        assert handle.container_id == "container-abc123"
        assert handle.status == "created"

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

    def test_given_valid_config_when_create_called_then_rootfs_is_read_only(
        self, manager, mock_client
    ):
        manager.create_container()
        call_kwargs = mock_client.containers.create.call_args
        assert call_kwargs.kwargs["read_only"] is True

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
    ):
        client = MagicMock()
        client.environment = {"PATH": "/usr/bin", "SECRET": "hidden", "HOME": "/home"}
        mock_container = MagicMock()
        mock_container.id = "c1"
        client.containers.create.return_value = mock_container

        mgr = ContainerManager(client, env_allowlist={"PATH", "HOME"})
        mgr.create_container()

        call_kwargs = client.containers.create.call_args
        env = call_kwargs.kwargs["environment"]
        assert "PATH" in env
        assert "HOME" in env
        assert "SECRET" not in env


# ── Commit 2: start, stop, destroy ──


class TestStartContainer:
    def test_given_created_container_when_start_called_then_status_becomes_running(self, manager):
        handle = manager.create_container()
        manager.start(handle)
        assert handle.status == "running"

    def test_given_created_container_when_start_called_then_repo_cloned_at_ref(
        self, manager, mock_client
    ):
        handle = manager.create_container()
        manager.start(handle, repo_ref="feat/test")
        handle._container.exec_run.assert_called()
        call_args = handle._container.exec_run.call_args_list
        # The git clone call should reference the branch
        git_clone_call = [c for c in call_args if "feat/test" in str(c)]
        assert len(git_clone_call) > 0

    def test_given_image_without_cc_when_start_called_then_raises_with_actionable_message(
        self, manager
    ):
        handle = manager.create_container()
        # Mock exec_run to simulate 'which claude' failing (exit code 1)
        handle._container.exec_run.return_value = (1, b"")
        with pytest.raises(ContainerCreationError, match="claude"):
            manager.start(handle)

    def test_given_image_with_cc_when_start_called_then_no_validation_error(self, manager):
        handle = manager.create_container()
        # Mock exec_run to simulate 'which claude' succeeding
        handle._container.exec_run.return_value = (0, b"/home/claude/.local/bin/claude")
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

    def test_given_stopped_container_when_destroy_with_retain_volume_then_workspace_preserved(
        self, manager
    ):
        handle = manager.create_container()
        manager.stop(handle)
        manager.destroy(handle, remove_volume=False)
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
        return ContainerManager(client)

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
