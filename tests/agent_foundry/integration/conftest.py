"""Shared fixtures for agent-foundry integration tests."""

from __future__ import annotations

import logging

import pytest

logger = logging.getLogger(__name__)


@pytest.fixture
def cleanup_volumes():
    """Force-remove workspace volumes minted during a test.

    ``ContainerManager.destroy()`` removes the container but preserves its
    workspace volume (session reuse). A test that mints a named volume and
    passes it to ``create_container`` / ``run_process`` must therefore
    remove the volume itself, or it leaks after the run. Append each volume
    name to the yielded list; teardown removes them all.

    A removal failure (e.g. the volume is still in use by a leaked container)
    is logged rather than swallowed silently — an invisible leak is how
    lingering volumes went unnoticed before.
    """
    names: list[str] = []
    yield names
    if not names:
        return
    import docker
    import docker.errors

    client = docker.from_env()
    for name in names:
        try:
            client.volumes.get(name).remove(force=True)
        except docker.errors.NotFound:
            pass
        except Exception:
            logger.warning("failed to remove test volume %s (leaked?)", name, exc_info=True)
