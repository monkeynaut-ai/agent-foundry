"""Container lifecycle manager wrapping Docker SDK.

Provides generic container creation, start, stop, destroy, and file I/O.
Products configure the manager with their image, env vars, and constraints.
"""

import io
import logging
import os
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent_foundry.acp.errors import ContainerCreationError, ContainerLifecycleError

logger = logging.getLogger(__name__)

# Minimal env vars safe to forward into any agent container
DEFAULT_ENV_ALLOWLIST = {
    "LANG",
    "TERM",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
}


class ContainerConfig(BaseModel):
    """Generic container resource constraints.

    Products may extend or compose with this for domain-specific fields.
    """

    mem_limit_mb: int = 1024
    cpu_quota: int = 100_000
    pids_limit: int = 256


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
        default_image: str,
        env_allowlist: set[str] | None = None,
    ):
        self._client = client
        self._default_image = default_image
        self._env_allowlist = env_allowlist or DEFAULT_ENV_ALLOWLIST
        self._handles: list[ContainerHandle] = []

    def create_container(
        self,
        image: str | None = None,
        workspace_volume: str = "",
        constraints: Any = None,
        extra_env: dict[str, str] | None = None,
    ) -> ContainerHandle:
        """Create a container with safety baseline enforced."""
        image = image or self._default_image
        constraints = constraints or ContainerConfig()

        volumes = {}
        if workspace_volume:
            volumes[workspace_volume] = {"bind": "/workspace", "mode": "rw"}

        environment = {k: v for k, v in os.environ.items() if k in self._env_allowlist}
        if extra_env:
            environment.update(extra_env)

        try:
            container = self._client.containers.create(
                image,
                detach=True,
                user="1000:1000",
                cap_drop=["ALL"],
                read_only=False,
                tmpfs={"/tmp": "size=256m"},
                volumes=volumes,
                mem_limit=f"{constraints.mem_limit_mb}m",
                environment=environment,
                extra_hosts={"host.docker.internal": "host-gateway"},
                cpu_quota=constraints.cpu_quota,
                pids_limit=constraints.pids_limit,
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

    def start(self, handle: ContainerHandle) -> None:
        """Start a container."""
        try:
            handle._container.start()
            handle._container.reload()
            handle.status = "running"
        except (ContainerCreationError, ContainerLifecycleError):
            raise
        except Exception as e:
            raise ContainerLifecycleError(str(e), container_id=handle.container_id) from e

    def validate_image(
        self,
        handle: ContainerHandle,
        required_commands: list[str] | None = None,
    ) -> None:
        """Verify required commands are available in the container image."""
        if required_commands is None:
            required_commands = ["claude"]

        for cmd in required_commands:
            exit_code, _ = handle._container.exec_run(f"which {cmd}")
            if exit_code != 0:
                raise ContainerCreationError(
                    f"Required command '{cmd}' not found in container image. "
                    f"Ensure the Docker image includes '{cmd}' "
                    f"before using it with the Docker worker.",
                    image=self._default_image,
                )

    def stop(self, handle: ContainerHandle, timeout: int = 10) -> None:
        """Stop a container gracefully."""
        try:
            handle._container.stop(timeout=timeout)
            handle.status = "stopped"
        except Exception as e:
            raise ContainerLifecycleError(str(e), container_id=handle.container_id) from e

    def destroy(self, handle: ContainerHandle) -> None:
        """Remove a container. Workspace volumes are always preserved."""
        try:
            handle._container.remove(v=False)
            handle.status = "destroyed"
        except Exception as e:
            raise ContainerLifecycleError(str(e), container_id=handle.container_id) from e

    def read_file_from_container(self, handle: ContainerHandle, path: str) -> str | None:
        """Read a file from inside a container. Returns None if not found."""
        try:
            chunks, _ = handle._container.get_archive(path)
            raw = b"".join(chunks)
            with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
                member = tar.getmembers()[0]
                f = tar.extractfile(member)
                if f is None:
                    return None
                return f.read().decode()
        except Exception:
            return None

    def copy_from_container(
        self, handle: ContainerHandle, container_path: str, host_path: Path
    ) -> bool:
        """Copy a file from inside a container to the host filesystem."""
        content = self.read_file_from_container(handle, container_path)
        if content is None:
            return False
        host_path.parent.mkdir(parents=True, exist_ok=True)
        host_path.write_text(content)
        return True

    def write_file_to_container(
        self, handle: ContainerHandle, container_path: str, content: str
    ) -> None:
        """Write a file into a container via put_archive."""
        dir_path = os.path.dirname(container_path)
        filename = os.path.basename(container_path)
        buf = io.BytesIO()
        data = content.encode()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=filename)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        buf.seek(0)
        handle._container.put_archive(dir_path, buf)

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
