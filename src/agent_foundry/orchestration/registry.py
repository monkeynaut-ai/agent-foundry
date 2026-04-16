"""AgentContainerRegistry — one container per AgentAction per run.

Lazy, identity-keyed ``get_or_create``; synchronous
``record_session_id``; idempotent, failure-tolerant ``shutdown_all``;
emits ``agent_container_started`` lifecycle events on first creation.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agent_foundry.orchestration.env import build_container_env
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent

if TYPE_CHECKING:
    from agent_foundry.orchestration.lifecycle_writer import LifecycleWriter
    from agent_foundry.primitives.models import AgentAction

logger = logging.getLogger(__name__)

ROLE_INSTRUCTIONS_PATH = "/home/claude/role-instructions.md"

# Maximum seconds to wait for the container's Docker health check to
# report ``healthy`` before raising. The base ACP image's HEALTHCHECK
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

    handle: Any
    manager: Any
    session_id: str | None = None
    primitive_id: int | None = None
    agent_name: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


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
        manager: Any | None = None,
        oauth_token: str | None = None,
        inject_instructions: bool = False,
        health_wait_timeout_seconds: float = _DEFAULT_HEALTH_WAIT_TIMEOUT_SECONDS,
        wait_for_health: bool = False,
    ) -> None:
        self._workspace_volume = workspace_volume
        self._base_image_tag = base_image_tag
        self._docker_client_factory = docker_client_factory
        self._manager_override = manager
        self._oauth_token = oauth_token
        self._inject_instructions = inject_instructions
        self._health_wait_timeout_seconds = health_wait_timeout_seconds
        self._wait_for_health = wait_for_health
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
    ) -> LiveContainer:
        """Return the live container for ``primitive``, creating it if absent.

        Emits an ``agent_container_started`` lifecycle event on first
        creation (not on cache hits). Identity-keyed by ``id(primitive)``.
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
                None,
                self._extra_env_for(primitive),
            )
            # If configured to inject role instructions, write them before
            # start so the base-image entrypoint's append block sees them
            # on boot (matches ``create_for_invocation`` semantics).
            if self._inject_instructions:
                instructions_text = primitive.instructions_provider()
                await asyncio.to_thread(
                    manager.write_file_to_container,
                    handle,
                    ROLE_INSTRUCTIONS_PATH,
                    instructions_text,
                )
            await asyncio.to_thread(manager.start, handle)
            if self._wait_for_health:
                await self._wait_until_healthy(handle)
            live = LiveContainer(
                handle=handle,
                manager=manager,
                primitive_id=pid,
                agent_name=agent_name,
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
                cid = getattr(live.handle, "container_id", "<unknown>")
                logger.warning(
                    "destroy failed for %s (%s): %s",
                    live.agent_name,
                    cid,
                    exc,
                )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_manager(self) -> Any:
        """Construct a :class:`ContainerManager` from the injected factory.

        ``docker`` is imported lazily in the default-factory fallback so
        test environments without the docker SDK can still import this
        module.
        """
        from agent_foundry.acp.container import ContainerManager

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
        """
        if self._oauth_token is None:
            return {}
        return build_container_env(
            primitive,
            oauth_token=self._oauth_token,
            role_instructions_path=ROLE_INSTRUCTIONS_PATH,
        )

    async def _wait_until_healthy(self, handle: Any) -> None:
        """Poll the container's Docker HEALTHCHECK status until ``healthy``.

        The base ACP image declares a HEALTHCHECK that tests for
        ``/tmp/.container-ready`` — a marker file the entrypoint
        touches as its final setup step. Polling the health state
        (rather than sleeping a fixed interval) avoids races between
        the host's ``exec_run`` calls and the entrypoint's setup work
        (auth, lockdown, role-instructions append, plugin install).

        No-op when the handle does not expose a real Docker container
        (e.g. test fakes) — fakes start in a stable state immediately.
        Raises ``RuntimeError`` when the container reports ``unhealthy``
        or when the timeout elapses without reaching ``healthy``.
        """
        inner = getattr(handle, "_container", None)
        if inner is None:
            return

        reload_fn = getattr(inner, "reload", None)
        if reload_fn is None:
            return

        deadline = time.monotonic() + self._health_wait_timeout_seconds
        last_status: str | None = None
        while time.monotonic() < deadline:
            await asyncio.to_thread(reload_fn)
            attrs = getattr(inner, "attrs", None) or {}
            health = attrs.get("State", {}).get("Health", {}) or {}
            last_status = health.get("Status")
            if last_status == "healthy":
                return
            if last_status == "unhealthy":
                raise RuntimeError(
                    self._format_health_failure(
                        inner,
                        reason=f"container reported unhealthy (health={health!r})",
                    )
                )
            # ``starting`` or no HEALTHCHECK configured — keep polling.
            # If the image has no HEALTHCHECK, ``health`` is empty and
            # we'd loop forever; fall through to status-based readiness.
            if not health and getattr(inner, "status", None) == "running":
                return
            await asyncio.sleep(_HEALTH_POLL_INTERVAL_SECONDS)

        raise RuntimeError(
            self._format_health_failure(
                inner,
                reason=(
                    f"container did not become healthy within "
                    f"{self._health_wait_timeout_seconds:.1f}s "
                    f"(last_status={last_status!r})"
                ),
            )
        )

    def _format_health_failure(self, inner: Any, *, reason: str) -> str:
        logs = ""
        logs_fn = getattr(inner, "logs", None)
        if logs_fn is not None:
            try:
                raw = logs_fn(tail=80)
                logs = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
            except Exception:
                logs = "<unable to read container logs>"
        failed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return f"{reason} (checked_at={failed_at}); logs=\n{logs}"
