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
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agent_foundry.agents.errors import ContainerCreationError, ContainerLifecycleError

logger = logging.getLogger(__name__)

# Minimal env vars safe to forward into any agent container
DEFAULT_ENV_ALLOWLIST = {
    "LANG",
    "TERM",
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
    pids_limit: int = 2048


class ExecResult(BaseModel):
    """Typed result of running one command inside a container via
    :meth:`ContainerManagerBase.exec_run`.

    ``output`` is the combined stdout + stderr blob (the manager always
    requests demuxed=False so callers don't have to care about the
    docker SDK's two-tuple shape).
    """

    exit_code: int
    output: bytes


class HealthStatus(StrEnum):
    """Container health states surfaced by
    :meth:`ContainerManagerBase.health_status`.

    Values mirror Docker's reported HEALTHCHECK states with one
    addition: ``NONE`` covers the case where the image declares no
    HEALTHCHECK and the container is otherwise running. Callers that
    want to wait for the container to reach a steady state should treat
    ``NONE`` as "ready" (no other state is going to arrive).
    """

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"
    NONE = "none"


class HealthReport(BaseModel):
    """Snapshot of container health.

    ``status`` drives orchestration decisions; ``raw`` exposes the
    underlying ``State.Health`` block (FailingStreak, Log entries, …)
    so a registry that wants to surface a diagnostic message on
    timeout has the full payload to format.
    """

    status: HealthStatus
    raw: dict[str, Any] = Field(default_factory=dict)


@dataclass
class ContainerHandleBase:
    """Abstract base for container handles.

    Declares the attribute surface shared by the production
    :class:`ContainerHandle` and test fakes. The base intentionally
    carries no docker-SDK shape — the production
    :class:`ContainerHandle` subclass owns that escape hatch
    (``_container``), so future container backends (codex-in-a-
    container, podman, k8s) can implement
    :class:`ContainerManagerBase` against the base without inheriting
    docker-py types.

    Subclasses may add their own fields (e.g. ``created_at`` on the
    production handle, or test-observability fields on fakes).
    """

    container_id: str
    status: str = "created"
    workspace_path: str = ""


@dataclass
class ContainerHandle(ContainerHandleBase):
    """Handle to a managed Docker container.

    ``_container`` is the Any-typed escape hatch for the underlying
    docker-SDK container object — production :class:`ContainerManager`
    methods access it directly. Other backends subclass
    :class:`ContainerHandleBase` without inheriting this field.
    """

    _container: Any = field(default=None, repr=False)
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
    def exec_run(
        self,
        handle: ContainerHandleBase,
        cmd: list[str],
        *,
        user: str = _AGENT_USER,
        workdir: str | None = None,
    ) -> ExecResult:
        """Run ``cmd`` inside the container as ``user``; return a typed :class:`ExecResult`.

        ``cmd`` is a list of args (no shell). The combined stdout +
        stderr blob comes back as ``ExecResult.output`` regardless of
        the underlying transport.

        ``workdir`` sets the working directory for the executed command.
        When ``None``, the container image's WORKDIR is used.
        """

    @abstractmethod
    def read_logs(
        self,
        handle: ContainerHandleBase,
        *,
        tail: int | None = None,
        stdout: bool = True,
        stderr: bool = True,
        timestamps: bool = False,
    ) -> bytes:
        """Return container logs as bytes.

        ``tail`` limits the number of trailing lines (``None`` returns
        the full log). ``stdout`` / ``stderr`` toggle which streams are
        included. ``timestamps`` prepends per-line timestamps when True.
        """

    @abstractmethod
    def health_status(self, handle: ContainerHandleBase) -> HealthReport:
        """Return a snapshot of container health.

        Implementations are expected to refresh underlying state
        (``reload`` for the docker SDK) before answering so callers
        polling for a transition see fresh values.
        """

    @abstractmethod
    def inspect(self, handle: ContainerHandleBase) -> dict[str, Any]:
        """Return the container's full attrs dict (after refreshing state).

        Includes the fields exposed by ``docker inspect``: ``State`` (with
        ``ExitCode``, ``OOMKilled``, ``Status``), ``Mounts``, ``Config``,
        ``HostConfig``, etc. Callers read the keys they need; this method
        does not pre-pluck. Returns ``{}`` if the underlying transport
        has no attrs (defensive — production docker SDK always populates).
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

    def exec_run(
        self,
        handle: ContainerHandle,
        cmd: list[str],
        *,
        user: str = _AGENT_USER,
        workdir: str | None = None,
    ) -> ExecResult:
        """Run ``cmd`` inside the container as ``user``.

        Always passes ``demux=False`` so the docker SDK returns a single
        combined stdout+stderr blob. Supplementary GIDs are configured at
        container creation time via the ``SUPPLEMENTARY_GIDS`` env var read
        by the entrypoint — not at exec time (the Docker exec API does not
        support ``GroupAdd``).

        ``workdir`` sets the working directory; ``None`` defers to the
        container image's WORKDIR.
        """
        exit_code, output = handle._container.exec_run(cmd, demux=False, user=user, workdir=workdir)
        return ExecResult(exit_code=exit_code, output=output)

    def read_logs(
        self,
        handle: ContainerHandle,
        *,
        tail: int | None = None,
        stdout: bool = True,
        stderr: bool = True,
        timestamps: bool = False,
    ) -> bytes:
        """Return container logs as bytes.

        ``tail=None`` is mapped to docker's sentinel string ``"all"``
        (the SDK's documented way of asking for the whole log).
        """
        tail_arg: int | str = tail if tail is not None else "all"
        result = handle._container.logs(
            stdout=stdout,
            stderr=stderr,
            timestamps=timestamps,
            tail=tail_arg,
        )
        return result if isinstance(result, bytes) else b""

    def health_status(self, handle: ContainerHandle) -> HealthReport:
        """Reload the container's state and return a typed health snapshot.

        Maps ``State.Health.Status`` to :class:`HealthStatus`; absence of
        a Health subdict (image declares no HEALTHCHECK) maps to
        :attr:`HealthStatus.NONE`. Unknown status strings also map to
        ``NONE`` rather than raising — the caller decides whether to
        treat unknown as fatal.
        """
        handle._container.reload()
        attrs = handle._container.attrs or {}
        health = attrs.get("State", {}).get("Health", {}) or {}
        status_str = health.get("Status")
        if status_str == "healthy":
            status = HealthStatus.HEALTHY
        elif status_str == "unhealthy":
            status = HealthStatus.UNHEALTHY
        elif status_str == "starting":
            status = HealthStatus.STARTING
        else:
            status = HealthStatus.NONE
        return HealthReport(status=status, raw=dict(health))

    def inspect(self, handle: ContainerHandle) -> dict[str, Any]:
        """Reload the container and return its full docker-SDK attrs dict.

        Postmortem callers (container_executor's snapshot path) read
        ``State.ExitCode``, ``State.OOMKilled``, ``HostConfig.Memory``,
        ``Mounts``, etc. Reload first so the snapshot reflects current
        state (e.g. a container that has exited since handle creation).
        """
        handle._container.reload()
        attrs = handle._container.attrs
        return attrs if isinstance(attrs, dict) else {}

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
