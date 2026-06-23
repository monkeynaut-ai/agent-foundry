"""Integration test: ``ContainerConfig.network`` wires to Docker's ``--network``.

Proves the platform attaches a container to the requested network — the
default-deny ``none``, the default ``bridge``, and an arbitrary user-defined
network (the seam egress-filtered networks plug into) — by inspecting the
created container's ``HostConfig.NetworkMode``.

Hermetic: creates a throwaway user-defined network and never reaches the
internet. The container is created but not started — ``docker create`` already
records the network attachment, so no entrypoint/auth/health wait is needed.
"""

from __future__ import annotations

import contextlib
import os
import uuid

import pytest

from agent_foundry.agents.lifecycle import ContainerConfig, ContainerManager, NetworkMode

_BASE_IMAGE = os.environ.get("AGENT_BASE_IMAGE", "agent-worker:latest")


@pytest.fixture
def docker_client():
    try:
        import docker

        client = docker.from_env()
        client.ping()
    except Exception as e:
        pytest.skip(f"docker daemon unavailable: {e}")
    return client


def _network_mode(manager: ContainerManager, handle) -> str:
    return manager.inspect(handle).get("HostConfig", {}).get("NetworkMode", "")


@pytest.mark.integration
class TestContainerNetworkWiring:
    def test_given_default_when_create_called_then_attached_to_none(self, docker_client):
        manager = ContainerManager(client=docker_client, default_image=_BASE_IMAGE)
        handle = manager.create_container()
        try:
            assert _network_mode(manager, handle) == "none"
        finally:
            manager.destroy(handle)

    def test_given_bridge_when_create_called_then_attached_to_bridge(self, docker_client):
        manager = ContainerManager(client=docker_client, default_image=_BASE_IMAGE)
        handle = manager.create_container(constraints=ContainerConfig(network=NetworkMode.BRIDGE))
        try:
            assert _network_mode(manager, handle) == "bridge"
        finally:
            manager.destroy(handle)

    def test_given_named_network_when_create_called_then_attached_to_it(self, docker_client):
        net_name = f"af-net-test-{uuid.uuid4().hex[:8]}"
        network = docker_client.networks.create(net_name, driver="bridge")
        manager = ContainerManager(client=docker_client, default_image=_BASE_IMAGE)
        handle = None
        try:
            handle = manager.create_container(constraints=ContainerConfig(network=net_name))
            assert _network_mode(manager, handle) == net_name
        finally:
            if handle is not None:
                manager.destroy(handle)
            with contextlib.suppress(Exception):
                network.remove()
