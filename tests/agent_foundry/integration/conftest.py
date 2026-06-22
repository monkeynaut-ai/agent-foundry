"""Shared fixtures for agent-foundry integration tests."""

from __future__ import annotations

import contextlib

import pytest


@pytest.fixture
def cleanup_volumes():
    """Force-remove workspace volumes minted during a test.

    ``ContainerManager.destroy()`` removes the container but preserves its
    workspace volume (session reuse). A test that mints a named volume and
    passes it to ``create_container`` / ``run_process`` must therefore
    remove the volume itself, or it leaks after the run. Append each volume
    name to the yielded list; teardown removes them all.
    """
    names: list[str] = []
    yield names
    if not names:
        return
    import docker

    client = docker.from_env()
    for name in names:
        with contextlib.suppress(Exception):
            client.volumes.get(name).remove(force=True)
