"""Docker worker container lifecycle — unit tests with mocked Docker SDK."""

from unittest.mock import MagicMock

import pytest

from archipelago.docker_worker.container import ContainerHandle, ContainerManager
from archipelago.docker_worker.models import WorkerConstraints


@pytest.fixture
def mock_client():
    client = MagicMock()
    mock_container = MagicMock()
    mock_container.id = "container-abc123"
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
        constraints = WorkerConstraints()
        manager.create_container(constraints=constraints)
        call_kwargs = mock_client.containers.create.call_args
        assert call_kwargs.kwargs["tmpfs"] == {"/tmp": "size=256m"}

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
        handle._container.exec_run.assert_called_once()
        call_args = handle._container.exec_run.call_args
        assert "feat/test" in call_args.args[0]


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
