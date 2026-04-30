"""Container lifecycle manager wrapping Docker SDK.

Provides generic container creation, start, stop, destroy, and file I/O.
Products configure the manager with their image, env vars, and constraints.
"""

import io
import logging
import os
import tarfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent_foundry.agents.errors import ContainerCreationError, ContainerLifecycleError

logger = logging.getLogger(__name__)

# Minimal env vars safe to forward into any agent container
DEFAULT_ENV_ALLOWLIST = {
    "LANG",
    "TERM",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
}

# In-container user that runs the agent. Hardcoded today; TD3 (typed
# ImageLayout) will lift this onto a per-image config when codex /
# alternate base images land.
_AGENT_USER = "claude"


class ContainerConfig(BaseModel):
    """Generic container resource constraints.

    Products may extend or compose with this for domain-specific fields.
    """

    mem_limit_mb: int = 1024
    cpu_quota: int = 100_000
    pids_limit: int = 256


class ExecResult(BaseModel):
    """Typed result of running one command inside a container via
    :meth:`ContainerManagerBase.exec_run`.

    ``output`` is the combined stdout + stderr blob (the manager always
    requests demuxed=False so callers don't have to care about the
    docker SDK's two-tuple shape).
    """

    exit_code: int
    output: bytes


@dataclass
class ContainerHandleBase:
    """Abstract base for container handles.

    Declares the attribute surface shared by the production
    :class:`ContainerHandle` and test fakes. ``_container`` is the
    Any-typed escape hatch for the underlying docker-SDK container
    object — production code sets it; fakes leave it ``None``.

    Subclasses may add their own fields (e.g. ``created_at`` on the
    production handle, or test-observability fields on fakes).
    """

    container_id: str
    status: str = "created"
    workspace_path: str = ""
    _container: Any = field(default=None, repr=False)


@dataclass
class ContainerHandle(ContainerHandleBase):
    """Handle to a managed Docker container."""

    created_at: float = field(default_factory=time.time)


class ContainerManagerBase(ABC):
    """Abstract base for container lifecycle managers.

    Declares the methods that
    :class:`~agent_foundry.orchestration.registry.AgentContainerRegistry`
    and
    :mod:`~agent_foundry.orchestration.container_executor` depend on.
    The production :class:`ContainerManager` and the test
    ``FakeContainerManager`` both subclass this so ``LiveContainer``
    can type its ``manager`` field concretely (rather than ``Any``)
    and LSP navigation works through the call surface.
    """

    @abstractmethod
    def create_container(
        self,
        image: str | None = None,
        workspace_volume: str = "",
        constraints: Any = None,
        extra_env: dict[str, str] | None = None,
    ) -> ContainerHandleBase: ...

    @abstractmethod
    def start(self, handle: ContainerHandleBase) -> None: ...

    @abstractmethod
    def stop(self, handle: ContainerHandleBase, timeout: int = 10) -> None: ...

    @abstractmethod
    def destroy(self, handle: ContainerHandleBase) -> None: ...

    @abstractmethod
    def read_file_from_container(self, handle: ContainerHandleBase, path: str) -> str | None: ...

    @abstractmethod
    def copy_from_container(
        self, handle: ContainerHandleBase, container_path: str, host_path: Path
    ) -> bool: ...

    @abstractmethod
    def write_file_to_container(
        self, handle: ContainerHandleBase, container_path: str, content: str
    ) -> None: ...

    @abstractmethod
    def exec_run(self, handle: ContainerHandleBase, cmd: list[str]) -> ExecResult:
        """Run ``cmd`` inside the container as the agent user; return
        a typed :class:`ExecResult`.

        ``cmd`` is a list of args (no shell). The combined stdout +
        stderr blob comes back as ``ExecResult.output`` regardless of
        the underlying transport.
        """


class ContainerManager(ContainerManagerBase):
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
                cap_drop=["ALL"],
                cap_add=["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"],
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

    def exec_run(self, handle: ContainerHandle, cmd: list[str]) -> ExecResult:
        """Run ``cmd`` inside the container as the agent user.

        Always passes ``demux=False`` so the docker SDK returns a
        single combined stdout+stderr blob; always passes
        ``user=_AGENT_USER`` so the agent process runs as the
        non-root user the base image set up. Both choices are
        platform contracts: callers cannot override them.
        """
        exit_code, output = handle._container.exec_run(cmd, demux=False, user=_AGENT_USER)
        return ExecResult(exit_code=exit_code, output=output)

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
