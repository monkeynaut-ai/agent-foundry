"""Integration tests — workspace filesystem lockdown is enforced in the container.

Exercises the lockdown.sh script's real behavior:

- `WORKSPACE_HIDDEN_DIRS` paths become completely inaccessible to the
  non-root `claude` user (chmod 000).
- `WORKSPACE_READONLY_DIRS` paths become readable but not writable
  (chmod -R a-w).

These tests boot a real container, pre-populate directories inside the
workspace volume via put_archive before start, wait for the entrypoint
(which runs lockdown.sh) to report healthy, then `exec_run` as `claude`
to verify observable behavior — not string patterns in the script.

Skipped gracefully when the Docker daemon is unavailable.
"""

from __future__ import annotations

import contextlib
import io
import os
import tarfile
import time
import uuid

import pytest

from agent_foundry.agents.lifecycle import ContainerManager

pytestmark = pytest.mark.integration


HEALTH_TIMEOUT_SECONDS = 90.0


def _seed_workspace_dirs(handle, dirnames: list[str]) -> None:
    """Create directories under /workspace by extracting a tar with canary files.

    Tar extract creates intermediate directories automatically, so placing
    `<dir>/canary.txt` in the archive yields `/workspace/<dir>/canary.txt`
    with `/workspace/<dir>` as a side effect.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for dirname in dirnames:
            data = b"canary\n"
            info = tarfile.TarInfo(name=f"{dirname}/canary.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    handle._container.put_archive("/workspace", buf)


def _wait_until_healthy(handle, timeout: float = HEALTH_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    last_status: str | None = None
    while time.monotonic() < deadline:
        handle._container.reload()
        health = handle._container.attrs.get("State", {}).get("Health", {}) or {}
        last_status = health.get("Status")
        if last_status == "healthy":
            return
        if last_status == "unhealthy":
            logs = handle._container.logs(tail=40).decode(errors="replace")
            raise AssertionError(f"container unhealthy: health={health!r}; logs={logs}")
        time.sleep(0.25)
    logs = handle._container.logs(tail=40).decode(errors="replace")
    raise AssertionError(
        f"container did not become healthy within {timeout}s "
        f"(last_status={last_status!r}); logs={logs}"
    )


def _exec_as_claude(handle, cmd: list[str]) -> tuple[int, str]:
    exit_code, output = handle._container.exec_run(cmd, demux=False, user="claude")
    return exit_code, output.decode(errors="replace")


@pytest.fixture(scope="module")
def docker_client():
    try:
        import docker

        client = docker.from_env()
        client.ping()
    except Exception as e:
        pytest.skip(f"docker daemon unavailable: {e}")
    return client


@pytest.fixture
def base_image() -> str:
    return os.environ.get("AGENT_BASE_IMAGE", "agent-worker:latest")


@pytest.fixture
def locked_down_container(docker_client, base_image):
    """Boot a container with /workspace/hidden locked down and
    /workspace/readonly read-only. Yields the handle; tears down after."""
    oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "test-token-for-lockdown")

    manager = ContainerManager(client=docker_client, default_image=base_image)
    workspace_volume = f"lockdown-{uuid.uuid4().hex[:8]}"

    handle = manager.create_container(
        workspace_volume=workspace_volume,
        extra_env={
            "CLAUDE_CODE_OAUTH_TOKEN": oauth_token,
            "AGENT_HOST_DRIVEN": "1",
            "WORKSPACE_HIDDEN_DIRS": "/workspace/hidden",
            "WORKSPACE_READONLY_DIRS": "/workspace/readonly",
        },
    )
    try:
        _seed_workspace_dirs(handle, ["hidden", "readonly"])
        manager.start(handle)
        _wait_until_healthy(handle)
        yield handle
    finally:
        with contextlib.suppress(Exception):
            manager.stop(handle, timeout=5)
        manager.destroy(handle)


class TestHiddenDirs:
    def test_given_hidden_dir_when_claude_user_lists_then_permission_denied(
        self, locked_down_container
    ):
        exit_code, output = _exec_as_claude(locked_down_container, ["ls", "/workspace/hidden"])
        assert exit_code != 0, f"expected ls on hidden dir to fail; got exit=0 output={output!r}"
        assert "Permission denied" in output or "permission denied" in output, (
            f"expected 'Permission denied' in stderr; got: {output!r}"
        )

    def test_given_hidden_dir_when_claude_user_reads_file_then_permission_denied(
        self, locked_down_container
    ):
        exit_code, output = _exec_as_claude(
            locked_down_container, ["cat", "/workspace/hidden/canary.txt"]
        )
        assert exit_code != 0, f"expected cat on hidden file to fail; got exit=0 output={output!r}"

    def test_given_hidden_dir_when_root_lists_then_still_accessible(self, locked_down_container):
        """chmod 000 blocks non-root users; root bypasses. Sanity check."""
        exit_code, output = locked_down_container._container.exec_run(
            ["ls", "/workspace/hidden"], user="root"
        )
        assert exit_code == 0, (
            f"root should still access hidden dir; got exit={exit_code} output={output!r}"
        )


class TestReadonlyDirs:
    def test_given_readonly_dir_when_claude_user_reads_then_succeeds(self, locked_down_container):
        exit_code, output = _exec_as_claude(
            locked_down_container, ["cat", "/workspace/readonly/canary.txt"]
        )
        assert exit_code == 0, (
            f"expected readonly dir to be readable; got exit={exit_code} output={output!r}"
        )
        assert "canary" in output

    def test_given_readonly_dir_when_claude_user_writes_then_permission_denied(
        self, locked_down_container
    ):
        exit_code, output = _exec_as_claude(
            locked_down_container,
            ["sh", "-c", "echo modified > /workspace/readonly/canary.txt"],
        )
        assert exit_code != 0, (
            f"expected write to readonly file to fail; got exit=0 output={output!r}"
        )

    def test_given_readonly_dir_when_claude_user_creates_new_file_then_permission_denied(
        self, locked_down_container
    ):
        exit_code, output = _exec_as_claude(
            locked_down_container,
            ["sh", "-c", "touch /workspace/readonly/new.txt"],
        )
        assert exit_code != 0, (
            f"expected creating file in readonly dir to fail; got exit=0 output={output!r}"
        )


class TestUnrestrictedDirs:
    """Baseline: directories not listed in the env vars remain writable."""

    def test_given_workspace_root_when_claude_user_writes_then_succeeds(
        self, locked_down_container
    ):
        exit_code, output = _exec_as_claude(
            locked_down_container,
            ["sh", "-c", "echo baseline > /workspace/baseline.txt && cat /workspace/baseline.txt"],
        )
        assert exit_code == 0, (
            f"expected /workspace write to succeed; got exit={exit_code} output={output!r}"
        )
        assert "baseline" in output
