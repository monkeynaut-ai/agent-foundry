"""Tests for ACP container lifecycle manager."""

import io
import tarfile
from unittest.mock import MagicMock

import pytest

from agent_foundry.acp.container import (
    DEFAULT_ENV_ALLOWLIST,
    ContainerConfig,
    ContainerHandle,
    ContainerManager,
)
from agent_foundry.acp.errors import ContainerCreationError, ContainerLifecycleError


@pytest.fixture
def mock_client():
    client = MagicMock()
    mock_container = MagicMock()
    mock_container.id = "container-abc123"
    mock_container.exec_run.return_value = (0, b"/usr/bin/claude")
    client.containers.create.return_value = mock_container
    return client


@pytest.fixture
def manager(mock_client):
    return ContainerManager(mock_client, default_image="test-agent:latest")


class TestContainerConfig:
    def test_given_default_config_when_constructed_then_has_sane_defaults(self):
        cfg = ContainerConfig()
        assert cfg.mem_limit_mb == 1024
        assert cfg.cpu_quota == 100_000
        assert cfg.pids_limit == 256


class TestDefaultEnvAllowlist:
    def test_given_default_allowlist_then_contains_only_generic_vars(self):
        assert "LANG" in DEFAULT_ENV_ALLOWLIST
        assert "ANTHROPIC_API_KEY" in DEFAULT_ENV_ALLOWLIST
        # Archipelago-specific vars should NOT be in the generic allowlist
        assert "ARCHIPELAGO_WS_URL" not in DEFAULT_ENV_ALLOWLIST
        assert "GITHUB_TOKEN" not in DEFAULT_ENV_ALLOWLIST


class TestCreateContainer:
    def test_given_valid_config_when_create_called_then_returns_handle(self, manager):
        handle = manager.create_container()
        assert isinstance(handle, ContainerHandle)
        assert handle.container_id == "container-abc123"
        assert handle.status == "created"

    def test_given_no_image_arg_when_create_called_then_uses_default_image(
        self, manager, mock_client
    ):
        manager.create_container()
        call_args = mock_client.containers.create.call_args
        assert call_args.args[0] == "test-agent:latest"

    def test_given_explicit_image_when_create_called_then_uses_provided_image(
        self, manager, mock_client
    ):
        manager.create_container(image="custom:v2")
        call_args = mock_client.containers.create.call_args
        assert call_args.args[0] == "custom:v2"

    def test_given_create_called_then_safety_baseline_enforced(self, manager, mock_client):
        manager.create_container()
        kw = mock_client.containers.create.call_args.kwargs
        assert kw["user"] == "1000:1000"
        assert kw["cap_drop"] == ["ALL"]
        assert kw["extra_hosts"] == {"host.docker.internal": "host-gateway"}

    def test_given_constraints_when_create_called_then_resource_limits_applied(
        self, manager, mock_client
    ):
        cfg = ContainerConfig(mem_limit_mb=2048, cpu_quota=50000, pids_limit=128)
        manager.create_container(constraints=cfg)
        kw = mock_client.containers.create.call_args.kwargs
        assert kw["mem_limit"] == "2048m"
        assert kw["cpu_quota"] == 50000
        assert kw["pids_limit"] == 128

    def test_given_env_allowlist_when_create_called_then_only_allowed_vars_passed(
        self, monkeypatch
    ):
        monkeypatch.setenv("ALLOWED_VAR", "yes")
        monkeypatch.setenv("SECRET_VAR", "no")

        client = MagicMock()
        client.containers.create.return_value = MagicMock(id="c1")

        mgr = ContainerManager(client, default_image="img:1", env_allowlist={"ALLOWED_VAR"})
        mgr.create_container()

        env = client.containers.create.call_args.kwargs["environment"]
        assert "ALLOWED_VAR" in env
        assert "SECRET_VAR" not in env

    def test_given_extra_env_when_create_called_then_extra_env_merged(self, manager, mock_client):
        manager.create_container(extra_env={"WS_URL": "ws://host:1234"})
        env = mock_client.containers.create.call_args.kwargs["environment"]
        assert env["WS_URL"] == "ws://host:1234"

    def test_given_docker_error_when_create_called_then_raises_container_creation_error(
        self, mock_client
    ):
        mock_client.containers.create.side_effect = RuntimeError("docker daemon down")
        mgr = ContainerManager(mock_client, default_image="img:1")
        with pytest.raises(ContainerCreationError, match="docker daemon down"):
            mgr.create_container()

    def test_given_default_image_required_then_constructor_requires_it(self, mock_client):
        # default_image has no default value — must be provided
        mgr = ContainerManager(mock_client, default_image="must-provide:latest")
        assert mgr._default_image == "must-provide:latest"


class TestStartStopDestroy:
    def test_given_created_container_when_start_called_then_status_running(self, manager):
        handle = manager.create_container()
        manager.start(handle)
        assert handle.status == "running"

    def test_given_running_container_when_stop_called_then_status_stopped(self, manager):
        handle = manager.create_container()
        manager.start(handle)
        manager.stop(handle, timeout=15)
        handle._container.stop.assert_called_once_with(timeout=15)
        assert handle.status == "stopped"

    def test_given_stopped_container_when_destroy_called_then_volumes_preserved(self, manager):
        handle = manager.create_container()
        manager.destroy(handle)
        handle._container.remove.assert_called_once_with(v=False)
        assert handle.status == "destroyed"

    def test_given_start_failure_when_start_called_then_raises_lifecycle_error(self, manager):
        handle = manager.create_container()
        handle._container.start.side_effect = RuntimeError("OOM")
        with pytest.raises(ContainerLifecycleError, match="OOM"):
            manager.start(handle)


class TestValidateImage:
    def test_given_claude_available_when_validate_called_then_no_error(self, manager):
        handle = manager.create_container()
        handle._container.exec_run.return_value = (0, b"/usr/bin/claude")
        manager.validate_image(handle)  # no raise

    def test_given_claude_missing_when_validate_called_then_raises(self, manager):
        handle = manager.create_container()
        handle._container.exec_run.return_value = (1, b"")
        with pytest.raises(ContainerCreationError, match="claude"):
            manager.validate_image(handle)

    def test_given_custom_commands_when_validate_called_then_checks_all(self, manager):
        handle = manager.create_container()
        # First command found, second not
        handle._container.exec_run.side_effect = [(0, b"ok"), (1, b"")]
        with pytest.raises(ContainerCreationError, match="node"):
            manager.validate_image(handle, required_commands=["git", "node"])


class TestCleanupAll:
    def test_given_multiple_containers_when_cleanup_all_then_all_destroyed(self):
        client = MagicMock()
        containers = []

        def _create(*a, **kw):
            c = MagicMock()
            c.id = f"c-{len(containers)}"
            containers.append(c)
            return c

        client.containers.create.side_effect = _create
        mgr = ContainerManager(client, default_image="img:1")
        h1 = mgr.create_container()
        h2 = mgr.create_container()
        mgr.cleanup_all()
        assert h1.status == "destroyed"
        assert h2.status == "destroyed"


def _make_tar_bytes(filename: str, content: str) -> bytes:
    buf = io.BytesIO()
    data = content.encode()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name=filename)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestContainerFileIO:
    def test_given_file_exists_when_read_then_returns_content(self, manager):
        handle = manager.create_container()
        tar_bytes = _make_tar_bytes("data.json", '{"ok": true}')
        handle._container.get_archive.return_value = (iter([tar_bytes]), {"size": len(tar_bytes)})
        result = manager.read_file_from_container(handle, "/workspace/data.json")
        assert result == '{"ok": true}'

    def test_given_file_missing_when_read_then_returns_none(self, manager):
        handle = manager.create_container()
        handle._container.get_archive.side_effect = Exception("not found")
        assert manager.read_file_from_container(handle, "/missing") is None

    def test_given_file_exists_when_copy_then_written_to_host(self, manager, tmp_path):
        handle = manager.create_container()
        tar_bytes = _make_tar_bytes("out.txt", "hello\n")
        handle._container.get_archive.return_value = (iter([tar_bytes]), {"size": len(tar_bytes)})
        dest = tmp_path / "out.txt"
        assert manager.copy_from_container(handle, "/workspace/out.txt", dest)
        assert dest.read_text() == "hello\n"

    def test_given_content_when_write_to_container_then_put_archive_called(self, manager):
        handle = manager.create_container()
        manager.write_file_to_container(handle, "/workspace/spec.json", '{"x":1}')
        handle._container.put_archive.assert_called_once()
        assert handle._container.put_archive.call_args.args[0] == "/workspace"
