"""Test fakes for the orchestration layer.

Provides:

* :class:`FakeContainerManager` / :class:`FakeContainerHandle` — minimal
  container lifecycle fake with scripted ``destroy`` / ``exec_run`` /
  ``read_file_from_container`` / ``copy_from_container``.
* :class:`FakeDockerClient` + :class:`FakeContainers` — the
  registry's ``docker_client_factory`` injection point.
* :class:`FakeClaudeCodeAdapter` — scripted adapter returning canned
  envelope payloads per turn (older ``run_turn`` shape used by the
  file-path verification tests).
* :class:`FakeRunTurn` (alias :class:`FakeClaudeCodeDriver`) — scripted
  ``run_turn`` callable matching the current executor contract,
  including stream-json line scripting and session-id tracking.
* :class:`FakeResponder` — scripted responder for clarification /
  permission round-trip tests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_foundry.agents.lifecycle import (
    ContainerHandleBase,
    ContainerManagerBase,
    ExecResult,
    HealthReport,
    HealthStatus,
)
from agent_foundry.orchestration.container_executor import TurnResult
from agent_foundry.responders.models import (
    ResponderContext,
    ResponderRequest,
    ResponderResponse,
)
from agent_foundry.responders.protocol import Responder


@dataclass
class FakeContainerHandle(ContainerHandleBase):
    files: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    exec_log: list[str] = field(default_factory=list)


class FakeContainerManager(ContainerManagerBase):
    """Minimal container manager fake.

    Scripting surface:
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
        # Keyed by tuple(cmd) so list-of-args input becomes hashable.
        self.exec_script: dict[tuple[str, ...], ExecResult] = {}
        self.destroyed_ids: list[str] = []
        # Host-side file-path verification: always-present so tests
        # that never trigger a read can still assert ``read_file_log == []``.
        self.read_file_script: dict[str, list[str | None]] = {}
        self.read_file_log: list[tuple[str, bool, int]] = []
        # Container logs: per-handle scripted bytes (default empty).
        self.logs_script: dict[str, bytes] = {}
        self.logs_log: list[tuple[str, dict[str, Any]]] = []
        # Health: per-handle scripted HealthReport. Default is HEALTHY
        # so tests that don't care about health checks still pass
        # registry's wait-for-healthy gate immediately.
        self.health_script: dict[str, HealthReport] = {}
        self.health_log: list[str] = []
        # Rich exec call log: each entry records cmd, user, and group_add
        # so tests can assert on GID threading.
        self.exec_calls: list[dict] = []

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
            workspace_path="/workspace",
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

    def exec_run(
        self,
        handle: FakeContainerHandle,
        cmd: list[str],
        *,
        user: str = "claude",
    ) -> ExecResult:
        handle.exec_log.append(" ".join(cmd))
        self.exec_calls.append({"cmd": cmd, "user": user})
        return self.exec_script.get(tuple(cmd), ExecResult(exit_code=0, output=b""))

    def read_logs(
        self,
        handle: FakeContainerHandle,
        *,
        tail: int | None = None,
        stdout: bool = True,
        stderr: bool = True,
        timestamps: bool = False,
    ) -> bytes:
        self.logs_log.append(
            (
                handle.container_id,
                {
                    "tail": tail,
                    "stdout": stdout,
                    "stderr": stderr,
                    "timestamps": timestamps,
                },
            )
        )
        return self.logs_script.get(handle.container_id, b"")

    def health_status(self, handle: FakeContainerHandle) -> HealthReport:
        self.health_log.append(handle.container_id)
        return self.health_script.get(
            handle.container_id, HealthReport(status=HealthStatus.HEALTHY)
        )

    # --- Host-side file-path verification hooks ------------------------------
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

    # --- Host-to-host file copy hook -----------------------------------------
    #
    # ``copy_file_script`` maps a container path to the string contents the
    # fake should write to the host target path. Missing keys produce a
    # ``False`` return (nothing copied). ``copy_file_log`` records every
    # ``(container_path, host_path, copied)`` call in order so snapshot
    # tests can assert on both the per-path request and the final file.
    copy_file_script: dict[str, str]
    copy_file_log: list[tuple[str, str, bool]]

    def copy_from_container(
        self, handle: FakeContainerHandle, container_path: str, host_path: Path
    ) -> bool:
        script = getattr(self, "copy_file_script", None)
        if script is None:
            self.copy_file_script = {}
            script = self.copy_file_script
        log = getattr(self, "copy_file_log", None)
        if log is None:
            self.copy_file_log = []
            log = self.copy_file_log
        content = script.get(container_path)
        copied = content is not None
        if copied:
            host_path.parent.mkdir(parents=True, exist_ok=True)
            host_path.write_text(content)
        log.append((container_path, str(host_path), copied))
        return copied

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


# --- Docker-client factory fakes ---------------------------------------------


@dataclass
class FakeDockerContainer:
    """Mimics the ``docker.models.containers.Container`` attribute surface
    used by :class:`ContainerManager`. Registry tests assert identity and
    lifecycle flags; ``exec_run`` returns a stub (0, b"") tuple.
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

    Construct with either ``canned_structured_output`` (single-response)
    or ``turn_script`` (FIFO list of envelope payloads returned one per
    ``run_turn`` call). Overflow past the scripted turns raises
    ``AssertionError`` so tests catch runaway retry loops loudly.
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


# --- Current driver-contract fakes -------------------------------------------


class FakeRunTurn:
    """Scripted ``run_turn`` callable for :func:`run_agent_in_container`.

    Matches the signature of :func:`container_executor._run_claude_turn`:
    ``async def(live, *, prompt, resume_session_id, schema) ->
    (envelope_dict, session_id)``.

    Tests pass an instance as ``run_turn=`` to ``run_agent_in_container``
    (or :func:`install_fake_run_turn` for the indirect path via
    ``run_primitive_plan``). The instance exposes ``calls`` for
    assertions about the prompt / resume id each turn saw.

    Parameters
    ----------
    turn_script:
        FIFO list of envelope-dict payloads returned one per invocation.
    session_ids:
        FIFO list of session ids matched up with ``turn_script`` positionally.
        If shorter than ``turn_script``, the last value repeats.
    """

    def __init__(
        self,
        *,
        turn_script: list[dict[str, Any]],
        session_ids: list[str | None] | None = None,
    ) -> None:
        if not turn_script:
            raise ValueError("FakeRunTurn requires non-empty turn_script")
        self._turn_script: list[dict[str, Any]] = list(turn_script)
        self._session_ids: list[str | None] = list(
            session_ids if session_ids is not None else ["sess-fake-123"]
        )
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        live: Any,
        *,
        prompt: str,
        resume_session_id: str | None,
        schema: dict[str, Any],
        model: str = "",
        skip_permissions: bool = False,
    ) -> TurnResult:
        self.calls.append(
            {
                "prompt": prompt,
                "resume": resume_session_id,
                "model": model,
                "skip_permissions": skip_permissions,
            }
        )
        assert self._turn_script, (
            f"FakeRunTurn called beyond scripted turn count (call #{len(self.calls)})"
        )
        envelope = self._turn_script.pop(0)
        if len(self._session_ids) > 1:
            sid = self._session_ids.pop(0)
        else:
            sid = self._session_ids[0] if self._session_ids else None
        return TurnResult(envelope=envelope, session_id=sid, raw_output=b"")


# Back-compat alias — some tests still refer to the old name.
FakeClaudeCodeDriver = FakeRunTurn


class FakeResponder(Responder):
    """Scripted responder for clarification / permission round-trip tests.

    ``answers`` is a FIFO list of answer strings returned one per
    ``respond()`` call. If ``raise_on_call`` is set, the responder raises
    that exception on the first call (used for the "responder failed"
    test case).
    """

    def __init__(
        self,
        *,
        answers: list[str] | None = None,
        raise_on_call: BaseException | None = None,
    ) -> None:
        self._answers: list[str] = list(answers or [])
        self._raise = raise_on_call
        self.calls: list[dict[str, Any]] = []

    async def respond(
        self, request: ResponderRequest, context: ResponderContext
    ) -> ResponderResponse:
        self.calls.append({"request": request, "context": context})
        if self._raise is not None:
            raise self._raise
        assert self._answers, (
            f"FakeResponder.respond called beyond scripted answer count (call #{len(self.calls)})"
        )
        return ResponderResponse(answer=self._answers.pop(0))
