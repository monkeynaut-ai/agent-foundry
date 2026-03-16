"""Shared fixtures for archipelago integration tests.

These tests require:
- Docker daemon available on the host
- acp-cc-worker:latest image built (pdm docker-base)
"""

import docker
import pytest

WORKER_IMAGE = "acp-cc-worker:latest"

# Same safety baseline as ContainerManager in src/agent_foundry/acp/container.py
_CAP_DROP = ["ALL"]
_CAP_ADD = ["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"]


@pytest.fixture(scope="session")
def docker_client():
    """Real Docker client. Skip all integration tests if Docker unavailable."""
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception:
        pytest.skip("Docker daemon not available")


@pytest.fixture(scope="session")
def worker_image(docker_client):
    """Ensure the base worker image exists."""
    try:
        docker_client.images.get(WORKER_IMAGE)
    except docker.errors.ImageNotFound:
        pytest.skip(f"{WORKER_IMAGE} not built. Run 'pdm docker-base' first.")
    return WORKER_IMAGE


@pytest.fixture(autouse=True)
def container_cleanup(docker_client):
    """Track and force-remove all containers created during a test."""
    containers = []
    yield containers
    for c in containers:
        try:
            c.stop(timeout=2)
        except Exception:
            pass
        try:
            c.remove(force=True)
        except Exception:
            pass


def run_in_container(
    docker_client,
    image: str,
    script: str,
    env: dict[str, str] | None = None,
    cleanup_list: list | None = None,
) -> tuple[int, str]:
    """Run a shell script in a fresh container and return (exit_code, output).

    The container uses the same cap_drop/cap_add as ContainerManager
    but overrides the entrypoint to 'sh' so we can run arbitrary scripts
    without needing Claude CLI auth.

    Args:
        docker_client: Real Docker client.
        image: Docker image to use.
        script: Shell script to execute via sh -c.
        env: Environment variables to pass into the container.
        cleanup_list: If provided, container is appended for autouse cleanup.

    Returns:
        Tuple of (exit_code, combined stdout+stderr output).
    """
    container = docker_client.containers.create(
        image,
        entrypoint="sh",
        command=["-c", script],
        cap_drop=_CAP_DROP,
        cap_add=_CAP_ADD,
        tmpfs={"/tmp": "size=256m"},
        environment=env or {},
    )
    if cleanup_list is not None:
        cleanup_list.append(container)

    try:
        container.start()
        result = container.wait(timeout=30)
        exit_code = result["StatusCode"]
        output = container.logs(stdout=True, stderr=True).decode()
        return exit_code, output
    except Exception:
        container.stop(timeout=2)
        raise
    finally:
        if cleanup_list is None:
            try:
                container.remove(force=True)
            except Exception:
                pass
