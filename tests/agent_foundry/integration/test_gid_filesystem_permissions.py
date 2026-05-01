"""Integration tests — GID-based filesystem permission enforcement.

Verifies that Linux group ownership + mode 775 correctly enforces read/write
access when processes run with different supplementary GIDs:

  (1) A process with the matching GID can write to a GID-owned (mode 775) dir.
  (2) A process without the GID cannot write (falls to "others" r-x bits).
  (3) The tests/ override: a parent dir owned by GID 1002 (mode 775) with a
      subdirectory overridden to GID 1003 — a process holding GID 1002 but
      not GID 1003 cannot write to the subdirectory.
  (4) The SUPPLEMENTARY_GIDS env var approach: a container that reads
      SUPPLEMENTARY_GIDS and adds the user to those groups before running a
      command gains write access to GID-owned dirs.

Uses alpine (not agent-worker) — these tests exercise OS-level enforcement
and require no Claude Code tooling. Skipped when Docker daemon unavailable.

The exec helper creates a user with the correct UID and desired supplementary
groups inside a fresh container, mimicking what the entrypoint does when it
reads SUPPLEMENTARY_GIDS and calls ``usermod -aG <gid> claude`` before gosu.

Note: the Docker exec API does not support GroupAdd (only ``docker run``
does). Supplementary groups are therefore configured at container startup via
the SUPPLEMENTARY_GIDS env var read by the entrypoint — not at exec time.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest

pytestmark = pytest.mark.integration

ALPINE_IMAGE = "alpine:latest"
GID_DOCUMENTS = 1001
GID_CODEBASE = 1002
GID_TESTS = 1003
AGENT_UID = 1000  # numeric UID for the agent user


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
def gid_workspace(docker_client):
    """Volume with GID-owned workspace directories.

    /workspace/documents         — owned by GID_DOCUMENTS, mode 775
    /workspace/codebase          — owned by GID_CODEBASE, mode 775
    /workspace/codebase/tests    — owned by GID_TESTS, mode 775 (override)

    The two chown calls on codebase/ run in order: parent first, then tests/
    override. Reversing would leave tests/ owned by GID_CODEBASE.
    """
    volume_name = f"gid-perm-test-{uuid.uuid4().hex[:8]}"
    docker_client.volumes.create(volume_name)
    try:
        docker_client.containers.run(
            ALPINE_IMAGE,
            remove=True,
            volumes={volume_name: {"bind": "/workspace", "mode": "rw"}},
            command=[
                "sh",
                "-c",
                (
                    f"mkdir -p /workspace/documents /workspace/codebase/tests"
                    f" && chown -R root:{GID_DOCUMENTS} /workspace/documents"
                    f" && chmod -R 775 /workspace/documents"
                    f" && chown -R root:{GID_CODEBASE} /workspace/codebase"
                    f" && chmod -R 775 /workspace/codebase"
                    f" && chown -R root:{GID_TESTS} /workspace/codebase/tests"
                    f" && chmod -R 775 /workspace/codebase/tests"
                ),
            ],
        )
        yield volume_name
    finally:
        with contextlib.suppress(Exception):
            docker_client.volumes.get(volume_name).remove(force=True)


def _exec_with_groups_checked(
    docker_client,
    volume_name: str,
    uid: int,
    gids: list[int],
    cmd: str,
) -> tuple[int, str]:
    """Run cmd inside a container as uid with supplementary gids; returns (exit_code, output).

    Mimics the entrypoint SUPPLEMENTARY_GIDS mechanism: starts as root,
    creates the groups, adds the user to them, then uses ``su`` to run cmd
    as that user. This is how the production entrypoint works when it reads
    SUPPLEMENTARY_GIDS and calls ``usermod -aG <gid> claude`` before gosu.
    """
    inner = cmd.replace("'", "'\"'\"'")  # escape single quotes for the outer sh
    parts = [f"adduser -D -u {uid} -G root agent_{uid} 2>/dev/null || true"]
    for gid in gids:
        parts.append(f"addgroup -g {gid} grp_{gid} 2>/dev/null || true")
    for gid in gids:
        parts.append(f"addgroup agent_{uid} grp_{gid} 2>/dev/null || true")
    parts.append(f"su agent_{uid} -s /bin/sh -c '{inner}'")
    setup = " ; ".join(parts)

    container = docker_client.containers.create(
        ALPINE_IMAGE,
        command=["sh", "-c", setup],
        volumes={volume_name: {"bind": "/workspace", "mode": "rw"}},
    )
    try:
        container.start()
        result = container.wait(timeout=15)
        output = container.logs(stdout=True, stderr=True)
        return result["StatusCode"], output.decode(errors="replace")
    finally:
        with contextlib.suppress(Exception):
            container.remove(force=True)


class TestGidWriteAccess:
    """A process with the matching GID can write; without it, cannot."""

    def test_given_documents_gid_when_writing_to_documents_dir_then_succeeds(
        self, docker_client, gid_workspace
    ):
        code, out = _exec_with_groups_checked(
            docker_client,
            gid_workspace,
            AGENT_UID,
            [GID_DOCUMENTS],
            "touch /workspace/documents/test.txt",
        )
        assert code == 0, f"expected write success; got exit={code} output={out!r}"

    def test_given_no_matching_gid_when_writing_to_documents_dir_then_fails(
        self, docker_client, gid_workspace
    ):
        code, _ = _exec_with_groups_checked(
            docker_client,
            gid_workspace,
            AGENT_UID,
            [],
            "touch /workspace/documents/test.txt",
        )
        assert code != 0

    def test_given_codebase_gid_when_writing_to_codebase_dir_then_succeeds(
        self, docker_client, gid_workspace
    ):
        code, out = _exec_with_groups_checked(
            docker_client,
            gid_workspace,
            AGENT_UID,
            [GID_CODEBASE],
            "touch /workspace/codebase/impl.py",
        )
        assert code == 0, f"expected write success; got exit={code} output={out!r}"

    def test_given_no_gids_when_reading_any_dir_then_succeeds(self, docker_client, gid_workspace):
        code, _ = _exec_with_groups_checked(
            docker_client,
            gid_workspace,
            AGENT_UID,
            [],
            "ls /workspace/documents && ls /workspace/codebase",
        )
        assert code == 0


class TestTestsDirGidOverride:
    """GID_CODEBASE members cannot write to tests/ (owned by GID_TESTS).

    The override: codebase/ is owned by GID_CODEBASE (mode 775), but
    codebase/tests/ is owned by GID_TESTS (mode 775). A process holding
    GID_CODEBASE but not GID_TESTS falls to "others" bits (r-x) on tests/.
    """

    def test_given_codebase_gid_when_writing_to_tests_subdir_then_fails(
        self, docker_client, gid_workspace
    ):
        code, _ = _exec_with_groups_checked(
            docker_client,
            gid_workspace,
            AGENT_UID,
            [GID_CODEBASE],
            "touch /workspace/codebase/tests/test_foo.py",
        )
        assert code != 0

    def test_given_tests_gid_when_writing_to_tests_subdir_then_succeeds(
        self, docker_client, gid_workspace
    ):
        code, out = _exec_with_groups_checked(
            docker_client,
            gid_workspace,
            AGENT_UID,
            [GID_TESTS],
            "touch /workspace/codebase/tests/test_foo.py",
        )
        assert code == 0, f"expected write success; got exit={code} output={out!r}"

    def test_given_codebase_gid_when_reading_tests_subdir_then_succeeds(
        self, docker_client, gid_workspace
    ):
        code, _ = _exec_with_groups_checked(
            docker_client,
            gid_workspace,
            AGENT_UID,
            [GID_CODEBASE],
            "ls /workspace/codebase/tests",
        )
        assert code == 0

    def test_given_both_gids_when_writing_to_tests_subdir_then_succeeds(
        self, docker_client, gid_workspace
    ):
        """An agent holding both GIDs can write anywhere — multi-resource access."""
        code, out = _exec_with_groups_checked(
            docker_client,
            gid_workspace,
            AGENT_UID,
            [GID_CODEBASE, GID_TESTS],
            "touch /workspace/codebase/impl.py && touch /workspace/codebase/tests/test_foo.py",
        )
        assert code == 0, f"expected both writes to succeed; got exit={code} output={out!r}"
