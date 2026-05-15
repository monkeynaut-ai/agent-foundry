"""AgentContainerRegistry — one container per AgentAction per run.

Lazy, identity-keyed ``get_or_create``; synchronous
``record_session_id``; idempotent, failure-tolerant ``shutdown_all``;
emits ``agent_container_started`` lifecycle events on first creation.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agent_foundry.agents.lifecycle import (
    ContainerHandleBase,
    ContainerManagerBase,
    HealthReport,
    HealthStatus,
)
from agent_foundry.agents.mcp_settings import build_claude_json_project_entry, build_mcp_permissions
from agent_foundry.orchestration.env import build_container_env
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent

if TYPE_CHECKING:
    from agent_foundry.orchestration.lifecycle_writer import LifecycleWriter
    from agent_foundry.primitives.models import AgentAction

logger = logging.getLogger(__name__)

ROLE_INSTRUCTIONS_PATH = "/home/claude/role-instructions.md"
MCP_SETTINGS_PATH = "/home/claude/.claude/settings.json"
CLAUDE_CONFIG_PATH = "/home/claude/.claude.json"

# Maximum seconds to wait for the container's Docker health check to
# report ``healthy`` before raising. The base Agent Container image's HEALTHCHECK
# uses ``--start-period=60s``; this timeout exceeds it so we don't race.
# The entrypoint's setup steps (auth, lockdown, role-instructions
# append, LSP plugin install, product-init) touch
# ``/tmp/.container-ready`` as the final step; Docker then reports
# ``healthy``.
_DEFAULT_HEALTH_WAIT_TIMEOUT_SECONDS = 90.0
_HEALTH_POLL_INTERVAL_SECONDS = 0.25


@dataclass
class LiveContainer:
    """One container bound to one AgentAction for the duration of one run.

    The ``primitive_id`` / ``agent_name`` / ``created_at`` fields are
    populated by :meth:`AgentContainerRegistry.get_or_create`.
    """

    handle: ContainerHandleBase
    manager: ContainerManagerBase
    session_id: str | None = None
    primitive_id: int | None = None
    agent_name: str | None = None
    # Supplementary GIDs passed to docker exec --group-add when Claude Code
    # is invoked. Populated from AgentAction.gids by get_or_create.
    gids: list[int] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Per-container invocation counter. Mutate via ``next_invocation()``
    # so the field stays encapsulated; reading is fine.
    _invocation_count: int = 0
    # Cumulative turn counter across all invocations of this container.
    # Monotonically increasing so artifact turn dirs are unique per run.
    _turn_count: int = 0

    def next_invocation(self) -> int:
        """Increment and return this container's invocation counter.

        Each call to :func:`run_agent_in_container` against the live
        container reserves the next invocation number; lifecycle events
        tag the resulting work with that integer.
        """
        self._invocation_count += 1
        return self._invocation_count

    def next_turn(self) -> int:
        """Increment and return this container's cumulative turn counter.

        Called at the start of every turn (including responder and
        verification retries within an invocation) so artifact turn
        directories are globally unique across all invocations.
        """
        self._turn_count += 1
        return self._turn_count


class AgentContainerRegistry:
    """One-container-per-AgentAction-per-run pool.

    Keyed by ``id(primitive)``. Creation is lazy (first call to
    :meth:`get_or_create`). :meth:`shutdown_all` is idempotent and
    tolerates per-container destroy failures — each failure is logged
    at WARNING and execution continues.

    Accepts either ``docker_client_factory`` (builds its own
    :class:`ContainerManager` from the returned client) or a pre-built
    ``manager`` (used by tests with :class:`FakeContainerManager`). At
    least one must be provided before :meth:`get_or_create` is called.
    """

    def __init__(
        self,
        *,
        workspace_volume: str,
        base_image_tag: str,
        docker_client_factory: Callable[[], Any] | None = None,
        manager: ContainerManagerBase | None = None,
        oauth_token: str | None = None,
        health_wait_timeout_seconds: float = _DEFAULT_HEALTH_WAIT_TIMEOUT_SECONDS,
    ) -> None:
        self._workspace_volume = workspace_volume
        self._base_image_tag = base_image_tag
        self._docker_client_factory = docker_client_factory
        self._manager_override = manager
        self._oauth_token = oauth_token
        self._health_wait_timeout_seconds = health_wait_timeout_seconds
        self._containers: dict[int, LiveContainer] = {}
        self._lock = asyncio.Lock()
        self._shut_down = False

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    async def get_or_create(
        self,
        primitive: AgentAction,
        *,
        lifecycle_writer: LifecycleWriter,
        agent_name: str,
        instructions: str | None = None,
    ) -> LiveContainer:
        """Return the live container for ``primitive``, creating it if absent.

        Emits an ``agent_container_started`` lifecycle event on first
        creation (not on cache hits). Identity-keyed by ``id(primitive)``.

        If ``instructions`` is provided, the string is written into the
        container at creation time. The caller (typically the compiler) is
        responsible for resolving ``primitive.instructions_provider(input_state)``
        against the per-invocation input state before calling; the registry
        takes the pre-resolved text.
        """
        pid = id(primitive)
        async with self._lock:
            if self._shut_down:
                raise RuntimeError("Registry is shut down")
            live = self._containers.get(pid)
            if live is not None:
                return live

            manager = self._manager_override or await asyncio.to_thread(self._build_manager)
            handle = await asyncio.to_thread(
                manager.create_container,
                self._base_image_tag,
                self._workspace_volume,
                primitive.container_config,
                self._extra_env_for(primitive),
            )
            # If configured to inject role instructions, write them before
            # start so the base-image entrypoint's append block sees them
            # on boot (matches ``create_for_invocation`` semantics).
            if instructions is not None:
                await asyncio.to_thread(
                    manager.write_file_to_container,
                    handle,
                    ROLE_INSTRUCTIONS_PATH,
                    instructions,
                )
            if primitive.mcp_servers:
                cwd = getattr(primitive, "cwd", None) or "/workspace"
                # Write MCP server definitions to .claude.json under projects[cwd].
                claude_json_raw = await asyncio.to_thread(
                    manager.read_file_from_container, handle, CLAUDE_CONFIG_PATH
                )
                try:
                    claude_json: dict = json.loads(claude_json_raw) if claude_json_raw else {}
                except json.JSONDecodeError:
                    claude_json = {}
                projects = claude_json.setdefault("projects", {})
                existing_project: dict = projects.get(cwd, {})
                project_entry = build_claude_json_project_entry(primitive.mcp_servers)
                merged_project = {**existing_project, **project_entry}
                projects[cwd] = merged_project
                await asyncio.to_thread(
                    manager.write_file_to_container,
                    handle,
                    CLAUDE_CONFIG_PATH,
                    json.dumps(claude_json),
                )
                # Write tool permissions to settings.json.
                settings_raw = await asyncio.to_thread(
                    manager.read_file_from_container, handle, MCP_SETTINGS_PATH
                )
                try:
                    settings: dict = json.loads(settings_raw) if settings_raw else {}
                except json.JSONDecodeError:
                    settings = {}
                mcp_perms = build_mcp_permissions(primitive.mcp_servers)
                merged_settings = {
                    **settings,
                    "permissions": {
                        **settings.get("permissions", {}),
                        "allow": (
                            settings.get("permissions", {}).get("allow", [])
                            + mcp_perms["permissions"]["allow"]
                        ),
                    },
                }
                await asyncio.to_thread(
                    manager.write_file_to_container,
                    handle,
                    MCP_SETTINGS_PATH,
                    json.dumps(merged_settings),
                )
            await asyncio.to_thread(manager.start, handle)
            await self._wait_until_healthy(manager, handle)
            live = LiveContainer(
                handle=handle,
                manager=manager,
                primitive_id=pid,
                agent_name=agent_name,
                gids=list(primitive.gids),
            )
            self._containers[pid] = live
            lifecycle_writer.append(
                LifecycleEvent.AGENT_CONTAINER_STARTED,
                agent_name=agent_name,
                container_id=handle.container_id,
            )
            return live

    def record_session_id(self, primitive: AgentAction, session_id: str) -> None:
        """Stamp the LiveContainer with the claude ``--resume`` session id.

        No-op if the primitive has never been registered via
        :meth:`get_or_create`.
        """
        live = self._containers.get(id(primitive))
        if live is not None:
            live.session_id = session_id

    async def shutdown_all(self) -> None:
        """Destroy every registered container.

        Idempotent (second call is a no-op). If one destroy raises, the
        exception is logged and the remaining destroys still run.
        """
        async with self._lock:
            if self._shut_down:
                return
            self._shut_down = True
            targets = list(self._containers.values())
            self._containers.clear()

        for live in targets:
            # Best-effort stop first; real containers refuse ``destroy``
            # while still running (409 Conflict) even though the handle
            # itself is resolvable. ``stop`` failures (fake manager,
            # already-stopped) are swallowed so ``destroy`` still runs.
            with contextlib.suppress(Exception):
                await asyncio.to_thread(live.manager.stop, live.handle, 5)
            try:
                await asyncio.to_thread(live.manager.destroy, live.handle)
            except Exception as exc:
                cid = live.handle.container_id
                logger.warning(
                    "destroy failed for %s (%s): %s",
                    live.agent_name,
                    cid,
                    exc,
                )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_manager(self) -> ContainerManagerBase:
        """Construct a :class:`ContainerManager` from the injected factory.

        ``docker`` is imported lazily in the default-factory fallback so
        test environments without the docker SDK can still import this
        module.
        """
        from agent_foundry.agents.lifecycle import ContainerManager

        if self._docker_client_factory is not None:
            client = self._docker_client_factory()
        else:
            import docker  # local import — tests without docker still import

            client = docker.from_env()
        return ContainerManager(client=client, default_image=self._base_image_tag)

    def _extra_env_for(self, primitive: AgentAction) -> dict[str, str]:
        """Compose the env dict passed to ``ContainerManager.create_container``.

        When the registry has been configured with ``oauth_token`` (the
        ``run_primitive_plan`` entry path), compose the full agent env via
        :func:`build_container_env` so the container boots with the
        Claude Code OAuth token and the instructions-path env var the
        entrypoint consumes. Tests that construct the registry without an
        ``oauth_token`` (the fake-driver path) get an empty env.

        ``SUPPLEMENTARY_GIDS`` is always injected when ``primitive.gids``
        is non-empty. The entrypoint reads this env var to add the ``claude``
        user to those groups before calling ``gosu claude`` — the only way
        to configure supplementary groups on a process, since the Docker exec
        API does not expose ``GroupAdd``.
        """
        env: dict[str, str] = {}
        if self._oauth_token is not None:
            env.update(
                build_container_env(
                    primitive,
                    oauth_token=self._oauth_token,
                    role_instructions_path=ROLE_INSTRUCTIONS_PATH,
                )
            )
        if primitive.gids:
            env["SUPPLEMENTARY_GIDS"] = ",".join(str(g) for g in primitive.gids)
        return env

    async def _wait_until_healthy(
        self, manager: ContainerManagerBase, handle: ContainerHandleBase
    ) -> None:
        """Poll ``manager.health_status`` until the container reports HEALTHY.

        The base Agent Container image declares a HEALTHCHECK that tests for
        ``/tmp/.container-ready`` — a marker file the entrypoint
        touches as its final setup step. Polling the typed health state
        (rather than sleeping a fixed interval) avoids races between
        the host's ``exec_run`` calls and the entrypoint's setup work
        (auth, lockdown, role-instructions append, plugin install).

        Treats :attr:`HealthStatus.NONE` as ready — a container with no
        HEALTHCHECK declared is considered ready immediately on the
        assumption that ``manager.start`` succeeded.
        Raises ``RuntimeError`` when the container reports
        :attr:`HealthStatus.UNHEALTHY` or when the timeout elapses
        without reaching HEALTHY.
        """
        deadline = time.monotonic() + self._health_wait_timeout_seconds
        last_report: HealthReport | None = None
        while time.monotonic() < deadline:
            report = await asyncio.to_thread(manager.health_status, handle)
            last_report = report
            if report.status is HealthStatus.HEALTHY:
                return
            if report.status is HealthStatus.UNHEALTHY:
                raise RuntimeError(
                    self._format_health_failure(
                        manager,
                        handle,
                        reason=f"container reported unhealthy (health={report.raw!r})",
                    )
                )
            if report.status is HealthStatus.NONE:
                # No HEALTHCHECK declared on the image. ``manager.start``
                # already succeeded; treat as ready and return.
                return
            # STARTING — keep polling.
            await asyncio.sleep(_HEALTH_POLL_INTERVAL_SECONDS)

        last_status = last_report.status.value if last_report is not None else None
        raise RuntimeError(
            self._format_health_failure(
                manager,
                handle,
                reason=(
                    f"container did not become healthy within "
                    f"{self._health_wait_timeout_seconds:.1f}s "
                    f"(last_status={last_status!r})"
                ),
            )
        )

    def _format_health_failure(
        self,
        manager: ContainerManagerBase,
        handle: ContainerHandleBase,
        *,
        reason: str,
    ) -> str:
        try:
            raw = manager.read_logs(handle, tail=80)
            logs = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
        except Exception:
            logs = "<unable to read container logs>"
        failed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return f"{reason} (checked_at={failed_at}); logs=\n{logs}"
