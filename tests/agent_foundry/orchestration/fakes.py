"""Test fakes for the orchestration layer.

F0 shape ships :class:`FakeContainerManager` / :class:`FakeContainerHandle`
and :class:`FakeClaudeCodeAdapter`. Phase B.4 adds :class:`FakeDockerClient`
+ :class:`FakeContainers` for the registry's ``docker_client_factory``
injection point, plus scripted ``destroy`` / ``exec_run`` on the manager
fake. F.3 extends further (stream-json line scripting, put_archive
round-trip).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeContainerHandle:
    container_id: str
    workspace_path: str = "/workspace"
    status: str = "created"
    files: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    exec_log: list[str] = field(default_factory=list)


class FakeContainerManager:
    """F0 shape extended for Phase B.4.

    New in B.4:
      - ``destroy_side_effects`` — per-container-id callable run inside
        ``destroy`` before the handle is marked destroyed. Use to script
        raises (``lambda: (_ for _ in ()).throw(RuntimeError("boom"))``
        or simpler ``raise`` inside a function) so tests can confirm that
        ``shutdown_all`` tolerates per-container failures.
      - ``exec_run`` — returns a scripted ``(exit_code, output)`` tuple or
        the default ``(0, b"")`` if nothing is scripted.
      - ``destroyed_ids`` — observable list of container ids destroyed
        in call order, so tests can confirm that a failing destroy does
        not short-circuit the remaining destroys.
    """

    def __init__(self) -> None:
        self.handles: list[FakeContainerHandle] = []
        self._next_id = 0
        self.destroy_side_effects: dict[str, Callable[[], None]] = {}
        self.exec_script: dict[str, tuple[int, bytes]] = {}
        self.destroyed_ids: list[str] = []
        # E.2 host-side file-path verification: always-present so tests
        # that never trigger a read can still assert ``read_file_log == []``.
        self.read_file_script: dict[str, list[str | None]] = {}
        self.read_file_log: list[tuple[str, bool, int]] = []

    def create_container(
        self,
        image: str | None = None,
        workspace_volume: str = "",
        constraints: Any = None,
        extra_env: dict[str, str] | None = None,
    ) -> FakeContainerHandle:
        self._next_id += 1
        h = FakeContainerHandle(
            container_id=f"fake-{self._next_id}",
            env=dict(extra_env or {}),
        )
        self.handles.append(h)
        return h

    def start(self, handle: FakeContainerHandle) -> None:
        handle.status = "running"

    def write_file_to_container(self, handle: FakeContainerHandle, path: str, content: str) -> None:
        handle.files[path] = content

    def destroy(self, handle: FakeContainerHandle) -> None:
        side_effect = self.destroy_side_effects.get(handle.container_id)
        if side_effect is not None:
            side_effect()  # may raise
        handle.status = "destroyed"
        self.destroyed_ids.append(handle.container_id)

    def stop(self, handle: FakeContainerHandle, timeout: int = 10) -> None:
        handle.status = "stopped"

    def exec_run(self, handle: FakeContainerHandle, cmd: str) -> tuple[int, bytes]:
        handle.exec_log.append(cmd)
        return self.exec_script.get(cmd, (0, b""))

    # --- E.2 host-side file-path verification hooks --------------------------
    #
    # ``read_file_script`` maps a container path to a FIFO list of values.
    # Each ``read_file_from_container(handle, path)`` call pops the head:
    #   - ``None`` means "file not present" (matches real ContainerManager's
    #     behavior when ``get_archive`` raises).
    #   - ``str`` means "here is the decoded content".
    # Once a path's script is exhausted, subsequent reads default to ``None``.
    #
    # ``read_file_log`` records every ``(path, result_is_none, size)`` call in
    # order so tests can assert per-path call counts.
    read_file_script: dict[str, list[str | None]]
    read_file_log: list[tuple[str, bool, int]]

    def read_file_from_container(self, handle: FakeContainerHandle, path: str) -> str | None:
        # Defensive init so tests that don't opt in still work; dataclass-style
        # init isn't used for this class so we lazily create the attrs.
        script = getattr(self, "read_file_script", None)
        if script is None:
            self.read_file_script = {}
            script = self.read_file_script
        log = getattr(self, "read_file_log", None)
        if log is None:
            self.read_file_log = []
            log = self.read_file_log
        queue = script.get(path)
        value: str | None = queue.pop(0) if queue else None
        log.append((path, value is None, 0 if value is None else len(value.encode())))
        return value


# --- Phase B.4 docker-client factory fakes ------------------------------------


@dataclass
class FakeDockerContainer:
    """Mimics the ``docker.models.containers.Container`` attribute surface
    used by :class:`ContainerManager`. B.4 tests only assert identity and
    lifecycle flags; F.3 will add exec_run scripting here.
    """

    container_id: str
    started: bool = False
    destroyed: bool = False
    status: str = "created"

    @property
    def id(self) -> str:
        """Alias for ``container_id``.

        ``ContainerManager.create_container`` wraps the raw docker
        container in a :class:`ContainerHandle` via ``container.id`` —
        the real docker SDK exposes that attribute, so the fake must
        too.
        """
        return self.container_id

    def start(self) -> None:
        self.started = True
        self.status = "running"

    def reload(self) -> None:  # no-op; status already set by start()
        return None

    def stop(self, timeout: int = 10) -> None:
        self.started = False
        self.status = "stopped"

    def remove(self, v: bool = False) -> None:
        self.destroyed = True
        self.status = "destroyed"

    def exec_run(self, cmd: str) -> tuple[int, bytes]:
        return (0, b"")


class FakeContainers:
    """Mimics ``docker_client.containers`` with just ``create``."""

    def __init__(self) -> None:
        self.created: list[FakeDockerContainer] = []

    def create(self, image: str, **kwargs: Any) -> FakeDockerContainer:
        c = FakeDockerContainer(container_id=f"fake-docker-{len(self.created)}")
        self.created.append(c)
        return c


@dataclass
class FakeDockerClient:
    containers: FakeContainers = field(default_factory=FakeContainers)


class FakeClaudeCodeAdapter:
    """Scripted adapter returning canned envelope payloads per turn.

    F0 only uses run_turn once per invocation and only supports
    success envelopes. F.3's inner-loop tests extend this fake.

    Phase E.2 adds ``turn_script``: a FIFO list of envelope payloads returned
    one-per-``run_turn``. Construct with either ``canned_structured_output``
    (legacy single-response) or ``turn_script`` (multi-turn). Overflow past
    the scripted turns raises ``AssertionError`` so tests catch runaway
    retry loops loudly.
    """

    def __init__(
        self,
        *,
        canned_structured_output: dict[str, Any] | None = None,
        turn_script: list[dict[str, Any]] | None = None,
    ) -> None:
        if canned_structured_output is None and turn_script is None:
            raise ValueError(
                "FakeClaudeCodeAdapter requires canned_structured_output or turn_script"
            )
        if canned_structured_output is not None and turn_script is not None:
            raise ValueError("Provide canned_structured_output OR turn_script, not both")
        self._canned = canned_structured_output
        self._turn_script: list[dict[str, Any]] = list(turn_script or [])
        self.calls: list[dict[str, Any]] = []

    async def run_turn(
        self,
        *,
        prompt: str,
        json_schema: dict[str, Any],
        resume_session_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"prompt": prompt, "schema": json_schema, "resume": resume_session_id})
        if self._canned is not None:
            return self._canned
        assert self._turn_script, (
            "FakeClaudeCodeAdapter.run_turn called beyond scripted turn count "
            f"(call #{len(self.calls)})"
        )
        return self._turn_script.pop(0)
