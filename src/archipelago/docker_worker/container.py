"""Container lifecycle manager wrapping Docker SDK."""

import time
from dataclasses import dataclass, field
from typing import Any

from archipelago.docker_worker.errors import ContainerCreationError, ContainerLifecycleError
from archipelago.docker_worker.models import WorkerConstraints

DEFAULT_ENV_ALLOWLIST = {"PATH", "HOME", "LANG", "TERM", "ANTHROPIC_API_KEY"}


@dataclass
class ContainerHandle:
    """Handle to a managed Docker container."""

    container_id: str
    status: str = "created"
    workspace_path: str = ""
    created_at: float = field(default_factory=time.time)
    _container: Any = field(default=None, repr=False)


class ContainerManager:
    """Manages Docker container lifecycle with safety baseline enforcement."""

    def __init__(
        self,
        client: Any,
        default_image: str = "python:3.13-slim",
        env_allowlist: set[str] | None = None,
    ):
        self._client = client
        self._default_image = default_image
        self._env_allowlist = env_allowlist or DEFAULT_ENV_ALLOWLIST
        self._handles: list[ContainerHandle] = []

    def create_container(
        self,
        image: str | None = None,
        repo_ref: str = "main",
        workspace_volume: str = "",
        constraints: WorkerConstraints | None = None,
    ) -> ContainerHandle:
        """Create a container with safety baseline enforced."""
        image = image or self._default_image
        constraints = constraints or WorkerConstraints()

        volumes = {}
        if workspace_volume:
            volumes[workspace_volume] = {"bind": "/workspace", "mode": "rw"}

        environment = {
            k: v for k, v in (self._client.environment or {}).items()
            if k in self._env_allowlist
        } if hasattr(self._client, "environment") else {}

        try:
            container = self._client.containers.create(
                image,
                command="sleep infinity",
                detach=True,
                user="1000:1000",
                cap_drop=["ALL"],
                read_only=True,
                tmpfs={"/tmp": "size=256m"},
                volumes=volumes,
                mem_limit=f"{constraints.timeout_seconds}m" if False else None,
                environment=environment,
                cpu_quota=getattr(constraints, "cpu_quota", None),
                pids_limit=getattr(constraints, "pids_limit", None),
            )
        except Exception as e:
            raise ContainerCreationError(str(e), image=image) from e

        handle = ContainerHandle(
            container_id=container.id,
            workspace_path="/workspace",
            _container=container,
        )
        self._handles.append(handle)
        return handle

    def start(self, handle: ContainerHandle, repo_ref: str = "main") -> None:
        """Start a container and clone the repo."""
        try:
            handle._container.start()
            handle.status = "running"
            handle._container.exec_run(
                f"git clone --branch {repo_ref} /repo /workspace || true",
                user="1000:1000",
            )
        except Exception as e:
            raise ContainerLifecycleError(str(e), container_id=handle.container_id) from e

    def stop(self, handle: ContainerHandle, timeout: int = 10) -> None:
        """Stop a container gracefully."""
        try:
            handle._container.stop(timeout=timeout)
            handle.status = "stopped"
        except Exception as e:
            raise ContainerLifecycleError(str(e), container_id=handle.container_id) from e

    def destroy(self, handle: ContainerHandle, remove_volume: bool = False) -> None:
        """Remove a container, optionally retaining the workspace volume."""
        try:
            handle._container.remove(v=remove_volume)
            handle.status = "destroyed"
        except Exception as e:
            raise ContainerLifecycleError(str(e), container_id=handle.container_id) from e

    def cleanup_all(self) -> None:
        """Emergency cleanup of all tracked containers."""
        for handle in self._handles:
            if handle.status not in ("destroyed",):
                try:
                    handle._container.stop(timeout=5)
                    handle._container.remove(v=False)
                    handle.status = "destroyed"
                except Exception:
                    pass
