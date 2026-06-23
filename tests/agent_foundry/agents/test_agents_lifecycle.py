"""Tests for Agent Container container lifecycle manager."""

import io
import tarfile
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from agent_foundry.agents.errors import ContainerCreationError, ContainerLifecycleError
from agent_foundry.agents.lifecycle import (
    DEFAULT_ENV_ALLOWLIST,
    ContainerConfig,
    ContainerHandle,
    ContainerManager,
    ExecResult,
    HealthReport,
    HealthStatus,
    NetworkMode,
)


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
        assert cfg.mem_limit_mb == 2048
        assert cfg.cpu_quota == 100_000
        assert cfg.pids_limit == 2048
        assert cfg.tmp_size_mb == 1024

    def test_given_default_config_when_constructed_then_egress_denied(self):
        # Safe by default: a container gets no network unless the product opts in.
        cfg = ContainerConfig()
        assert cfg.network == NetworkMode.NONE

    def test_given_custom_network_name_when_constructed_then_kept_as_string(self):
        # A user-defined (e.g. egress-filtered) network is passed by name.
        cfg = ContainerConfig(network="egress-filtered")
        assert cfg.network == "egress-filtered"

    @pytest.mark.parametrize("bad", ["host", "container:other"])
    def test_given_isolation_breaking_network_when_constructed_then_rejected(self, bad):
        with pytest.raises(ValidationError, match="dissolves container isolation"):
            ContainerConfig(network=bad)

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_given_blank_network_when_constructed_then_rejected(self, blank):
        # Docker reads an empty network as the default bridge — reject it so
        # misconfiguration fails loudly instead of silently enabling egress.
        with pytest.raises(ValidationError, match="must not be empty"):
            ContainerConfig(network=blank)


class TestDefaultEnvAllowlist:
    def test_given_default_allowlist_then_contains_only_generic_vars(self):
        assert "LANG" in DEFAULT_ENV_ALLOWLIST
        assert "CLAUDE_CODE_OAUTH_TOKEN" in DEFAULT_ENV_ALLOWLIST
        # Non-secret git identity vars forward so the worker's commit
        # author can be set from the host (or .env) without extra_env.
        assert "GIT_USER_NAME" in DEFAULT_ENV_ALLOWLIST
        assert "GIT_USER_EMAIL" in DEFAULT_ENV_ALLOWLIST
        # ANTHROPIC_API_KEY is intentionally excluded: containers authenticate
        # via CLAUDE_CODE_OAUTH_TOKEN, and the host may hold ANTHROPIC_API_KEY
        # for other purposes (e.g. list_claude_models). Forwarding both would
        # trigger the entrypoint's mutual-exclusion check.
        assert "ANTHROPIC_API_KEY" not in DEFAULT_ENV_ALLOWLIST
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
        assert "user" not in kw  # entrypoint owns user switching via gosu
        assert kw["cap_drop"] == ["ALL"]
        assert kw["cap_add"] == ["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"]
        # tini PID 1 reaps zombies from exec'd turns and forwards signals.
        assert kw["init"] is True

    def test_given_default_when_create_called_then_egress_denied(self, manager, mock_client):
        manager.create_container()
        kw = mock_client.containers.create.call_args.kwargs
        assert kw["network"] == "none"
        # host.docker.internal mapping needs the host gateway, which only
        # exists when the container is on a network — omit it under `none`.
        assert "extra_hosts" not in kw

    def test_given_bridge_network_when_create_called_then_egress_enabled(
        self, manager, mock_client
    ):
        manager.create_container(constraints=ContainerConfig(network=NetworkMode.BRIDGE))
        kw = mock_client.containers.create.call_args.kwargs
        assert kw["network"] == "bridge"
        assert kw["extra_hosts"] == {"host.docker.internal": "host-gateway"}

    def test_given_named_network_when_create_called_then_passed_through(self, manager, mock_client):
        manager.create_container(constraints=ContainerConfig(network="egress-filtered"))
        kw = mock_client.containers.create.call_args.kwargs
        assert kw["network"] == "egress-filtered"
        # A named network carries traffic, so the host-gateway alias applies.
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

    def test_given_create_called_then_tmpfs_uses_default_size(self, manager, mock_client):
        manager.create_container()
        kw = mock_client.containers.create.call_args.kwargs
        assert kw["tmpfs"] == {"/tmp": "size=1024m"}

    def test_given_tmp_size_config_when_create_called_then_tmpfs_size_applied(
        self, manager, mock_client
    ):
        manager.create_container(constraints=ContainerConfig(tmp_size_mb=2048))
        kw = mock_client.containers.create.call_args.kwargs
        assert kw["tmpfs"] == {"/tmp": "size=2048m"}

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

    def test_given_extra_volumes_when_create_called_then_merged_into_volumes(
        self, manager, mock_client
    ):
        manager.create_container(
            workspace_volume="ws-vol",
            extra_volumes={"/host/path/ca.crt": {"bind": "/etc/ca.crt", "mode": "ro"}},
        )
        volumes = mock_client.containers.create.call_args.kwargs["volumes"]
        # workspace volume still present
        assert volumes["ws-vol"] == {"bind": "/workspace", "mode": "rw"}
        # extra volume merged in
        assert volumes["/host/path/ca.crt"] == {"bind": "/etc/ca.crt", "mode": "ro"}

    def test_given_no_extra_volumes_when_create_called_then_volumes_unchanged(
        self, manager, mock_client
    ):
        manager.create_container(workspace_volume="ws-vol")
        volumes = mock_client.containers.create.call_args.kwargs["volumes"]
        assert volumes == {"ws-vol": {"bind": "/workspace", "mode": "rw"}}

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


class TestContainerHandleBaseEncapsulation:
    """Regression: the docker-SDK escape hatch is implementation
    detail of the production ContainerManager + ContainerHandle. The
    abstract ContainerHandleBase used by managers (and faked by tests)
    must NOT expose ``_container``. Future container backends
    (codex-in-a-container, podman, k8s) implement ContainerManagerBase
    against ContainerHandleBase without inheriting docker-py shape.
    """

    def test_container_handle_base_has_no_container_field(self):
        import dataclasses

        from agent_foundry.agents.lifecycle import ContainerHandleBase

        field_names = {f.name for f in dataclasses.fields(ContainerHandleBase)}
        assert "_container" not in field_names, (
            "ContainerHandleBase must not expose docker-SDK shape; "
            "_container belongs on ContainerHandle only."
        )

    def test_container_handle_subclass_keeps_container_field(self):
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(ContainerHandle)}
        assert "_container" in field_names


class TestExecResult:
    def test_exec_result_carries_exit_code_and_output(self):
        result = ExecResult(exit_code=0, output=b"hello")
        assert result.exit_code == 0
        assert result.output == b"hello"

    def test_exec_result_is_pydantic_model(self):
        # Pydantic validation: exit_code must coerce; bytes must be bytes.
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ExecResult(exit_code="not-an-int", output=b"")  # type: ignore[arg-type]


class TestExecRun:
    def test_exec_run_returns_exec_result(self, manager):
        handle = manager.create_container()
        handle._container.exec_run.return_value = (0, b"hello\n")
        result = manager.exec_run(handle, ["echo", "hello"])
        assert isinstance(result, ExecResult)
        assert result.exit_code == 0
        assert result.output == b"hello\n"

    def test_exec_run_passes_list_command_to_docker_sdk(self, manager):
        handle = manager.create_container()
        handle._container.exec_run.return_value = (0, b"")
        manager.exec_run(handle, ["claude", "-p", "hi"])
        call_args = handle._container.exec_run.call_args
        assert call_args.args[0] == ["claude", "-p", "hi"]

    def test_exec_run_runs_as_claude_user_by_default(self, manager):
        handle = manager.create_container()
        handle._container.exec_run.return_value = (0, b"")
        manager.exec_run(handle, ["whoami"])
        kw = handle._container.exec_run.call_args.kwargs
        assert kw["user"] == "claude"

    def test_exec_run_uses_demux_false_so_output_is_combined_bytes(self, manager):
        handle = manager.create_container()
        handle._container.exec_run.return_value = (1, b"err+out combined")
        manager.exec_run(handle, ["fail"])
        kw = handle._container.exec_run.call_args.kwargs
        assert kw["demux"] is False

    def test_exec_run_propagates_nonzero_exit(self, manager):
        handle = manager.create_container()
        handle._container.exec_run.return_value = (42, b"boom")
        result = manager.exec_run(handle, ["fail"])
        assert result.exit_code == 42
        assert result.output == b"boom"


class TestReadLogs:
    def test_read_logs_returns_bytes_for_full_log(self, manager):
        handle = manager.create_container()
        handle._container.logs.return_value = b"line1\nline2\n"
        out = manager.read_logs(handle)
        assert out == b"line1\nline2\n"

    def test_read_logs_passes_tail_kwarg_through(self, manager):
        handle = manager.create_container()
        handle._container.logs.return_value = b"tail"
        manager.read_logs(handle, tail=80)
        kw = handle._container.logs.call_args.kwargs
        assert kw["tail"] == 80

    def test_read_logs_default_includes_stdout_and_stderr_no_timestamps(self, manager):
        handle = manager.create_container()
        handle._container.logs.return_value = b""
        manager.read_logs(handle)
        kw = handle._container.logs.call_args.kwargs
        assert kw["stdout"] is True
        assert kw["stderr"] is True
        assert kw["timestamps"] is False

    def test_read_logs_respects_explicit_flags(self, manager):
        handle = manager.create_container()
        handle._container.logs.return_value = b""
        manager.read_logs(handle, stdout=False, stderr=True, timestamps=True)
        kw = handle._container.logs.call_args.kwargs
        assert kw["stdout"] is False
        assert kw["stderr"] is True
        assert kw["timestamps"] is True


class TestHealthStatus:
    def test_health_status_returns_healthy_when_state_health_status_is_healthy(self, manager):
        handle = manager.create_container()
        handle._container.attrs = {"State": {"Health": {"Status": "healthy"}}}
        report = manager.health_status(handle)
        assert isinstance(report, HealthReport)
        assert report.status is HealthStatus.HEALTHY

    def test_health_status_returns_unhealthy(self, manager):
        handle = manager.create_container()
        handle._container.attrs = {"State": {"Health": {"Status": "unhealthy"}}}
        report = manager.health_status(handle)
        assert report.status is HealthStatus.UNHEALTHY

    def test_health_status_returns_starting(self, manager):
        handle = manager.create_container()
        handle._container.attrs = {"State": {"Health": {"Status": "starting"}}}
        report = manager.health_status(handle)
        assert report.status is HealthStatus.STARTING

    def test_health_status_returns_none_when_no_healthcheck_configured(self, manager):
        handle = manager.create_container()
        # No "Health" subdict — image declares no HEALTHCHECK.
        handle._container.attrs = {"State": {"Status": "running"}}
        report = manager.health_status(handle)
        assert report.status is HealthStatus.NONE

    def test_health_status_calls_reload_to_refresh_state(self, manager):
        handle = manager.create_container()
        handle._container.attrs = {"State": {"Health": {"Status": "healthy"}}}
        manager.health_status(handle)
        handle._container.reload.assert_called_once()

    def test_health_report_carries_raw_state_for_diagnostics(self, manager):
        handle = manager.create_container()
        handle._container.attrs = {
            "State": {
                "Health": {
                    "Status": "unhealthy",
                    "FailingStreak": 3,
                    "Log": [{"Output": "boom"}],
                }
            }
        }
        report = manager.health_status(handle)
        # Raw block round-trips for downstream log formatting.
        assert report.raw["FailingStreak"] == 3
        assert report.raw["Log"][0]["Output"] == "boom"


class TestInspect:
    """`inspect` returns the container's full docker-SDK attrs dict
    (post-reload), so callers can read OOMKilled, ExitCode, State.Status,
    Mounts, HostConfig, etc. without each duplicating the reload+attrs
    boilerplate.
    """

    def test_inspect_returns_attrs_dict(self, manager):
        handle = manager.create_container()
        handle._container.attrs = {
            "State": {"Status": "exited", "ExitCode": 137, "OOMKilled": True}
        }
        out = manager.inspect(handle)
        assert out["State"]["ExitCode"] == 137
        assert out["State"]["OOMKilled"] is True

    def test_inspect_calls_reload_to_refresh_state(self, manager):
        # Without reload, the cached attrs from create_container may still
        # show "running" after the container has exited.
        handle = manager.create_container()
        handle._container.attrs = {"State": {"Status": "exited"}}
        manager.inspect(handle)
        handle._container.reload.assert_called_once()

    def test_inspect_returns_empty_dict_when_attrs_missing(self, manager):
        # Defensive: docker SDK never returns None for attrs in practice,
        # but the abstraction promises a dict, not Optional[dict].
        handle = manager.create_container()
        handle._container.attrs = {}
        assert manager.inspect(handle) == {}


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
