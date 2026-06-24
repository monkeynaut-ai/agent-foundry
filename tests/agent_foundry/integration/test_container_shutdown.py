"""Integration test: container shutdown hardening (#81).

Proves the `--init` (tini) PID 1 added by ``create_container``:

* is actually PID 1 in a started container (the reaping/signal-forwarding
  mechanism is in place), and
* yields a clean teardown when a turn is still running — ``stop`` + ``destroy``
  while a long-lived ``docker exec`` process is alive leaves no container or
  processes behind (the PID namespace is destroyed with the container).

Requires Docker and a CLAUDE_CODE_OAUTH_TOKEN (the base-image entrypoint
refuses to start without auth). Network stays default-deny — the container
reaches ``healthy`` offline.
"""

from __future__ import annotations

import contextlib
import os
import time

import pytest
from dotenv import load_dotenv

from agent_foundry.agents.lifecycle import ContainerManager

_REPO_ROOT_ENV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), ".env"
)
load_dotenv(_REPO_ROOT_ENV)

_BASE_IMAGE = os.environ.get("AGENT_BASE_IMAGE", "agent-worker:latest")
_HEALTH_TIMEOUT_S = 90.0


@pytest.fixture
def docker_client():
    try:
        import docker

        client = docker.from_env()
        client.ping()
    except Exception as e:
        pytest.skip(f"docker daemon unavailable: {e}")
    return client


def _start_idle_container(manager: ContainerManager):
    """Create + start a host-driven container and wait until healthy."""
    oauth_token = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
    handle = manager.create_container(
        extra_env={"CLAUDE_CODE_OAUTH_TOKEN": oauth_token, "AGENT_HOST_DRIVEN": "1"},
    )
    manager.start(handle)
    deadline = time.monotonic() + _HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        if manager.health_status(handle).status.value == "healthy":
            return handle
        time.sleep(0.25)
    logs = handle._container.logs(tail=40).decode(errors="replace")
    manager.destroy(handle)
    raise AssertionError(
        f"container did not become healthy within {_HEALTH_TIMEOUT_S}s; logs={logs}"
    )


@pytest.mark.integration
class TestContainerShutdown:
    def test_given_init_when_started_then_pid1_is_init_shim(self, docker_client):
        manager = ContainerManager(client=docker_client, default_image=_BASE_IMAGE)
        handle = _start_idle_container(manager)
        try:
            # tini installed by `--init` runs as PID 1 (docker-init / tini),
            # not the idle `tail`.
            comm = manager.exec_run(handle, ["cat", "/proc/1/comm"], user="root").output
            assert b"init" in comm or b"tini" in comm, f"PID 1 comm was {comm!r}"
        finally:
            with contextlib.suppress(Exception):
                manager.stop(handle, timeout=5)
            manager.destroy(handle)

    def test_given_turn_in_flight_when_torn_down_then_no_residue(self, docker_client):
        manager = ContainerManager(client=docker_client, default_image=_BASE_IMAGE)
        handle = _start_idle_container(manager)
        cid = handle.container_id
        # Simulate a turn still running at teardown: a long-lived exec process.
        handle._container.exec_run(["sleep", "300"], detach=True, user="root")

        manager.stop(handle, timeout=5)
        manager.destroy(handle)

        # Container (and its PID namespace, hence all processes) is gone.
        # Query by id rather than enumerating all containers: an unscoped
        # containers.list(all=True) races concurrent teardown in other
        # integration tests — docker-py inspects each enumerated container and
        # 404s if one is removed mid-iteration.
        import docker.errors

        with pytest.raises(docker.errors.NotFound):
            docker_client.containers.get(cid)
        assert handle.status == "destroyed"
