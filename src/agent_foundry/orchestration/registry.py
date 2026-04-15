"""AgentContainerRegistry — one container per AgentAction per run.

Phase B.4 shape: lazy, identity-keyed ``get_or_create``; synchronous
``record_session_id``; idempotent, failure-tolerant ``shutdown_all``;
emits ``agent_container_started`` lifecycle events on first creation.

The F0 helper pair (``create_for_invocation`` / ``destroy``) is preserved
as a thin wrapper around the underlying :class:`ContainerManager` so the
F0 executor (``container_executor.run_agent_in_container``) continues to
work unchanged. It bypasses the ``_containers`` identity map — F0
semantics are one-container-per-invocation, destroyed in the executor's
``finally``. The new B.4 API is the path future phases will use.
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
_ENTRYPOINT_SETUP_WAIT_SECONDS = 2.0


@dataclass
class LiveContainer:
    """One container bound to one AgentAction for the duration of one run.

    The ``primitive_id`` / ``agent_name`` / ``created_at`` fields are
    populated by :meth:`AgentContainerRegistry.get_or_create`. The F0
    ``create_for_invocation`` path leaves them at their defaults — it
    does not register the container in the identity map.
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

    Accepts either ``docker_client_factory`` (new B.4 path — builds its
    own :class:`ContainerManager`) or a pre-built ``manager`` (F0 compat
    path used by ``create_for_invocation``). At least one must be
    provided before :meth:`get_or_create` is called.
    """

    def __init__(
        self,
        *,
        workspace_volume: str,
        base_image_tag: str,
        docker_client_factory: Callable[[], Any] | None = None,
        manager: Any | None = None,
    ) -> None:
        self._workspace_volume = workspace_volume
        self._base_image_tag = base_image_tag
        self._docker_client_factory = docker_client_factory
        self._manager_override = manager
        self._containers: dict[int, LiveContainer] = {}
        self._lock = asyncio.Lock()
        self._shut_down = False

    # ------------------------------------------------------------------
    # Phase B.4 API
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
            await asyncio.to_thread(manager.start, handle)
            live = LiveContainer(
                handle=handle,
                manager=manager,
                primitive_id=pid,
                agent_name=agent_name,
            )
            self._containers[pid] = live
            lifecycle_writer.append(
                {
                    "type": LifecycleEvent.AGENT_CONTAINER_STARTED,
                    "agent_name": agent_name,
                    "container_id": handle.container_id,
                }
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
    # F0 compat path — thin wrapper preserved for container_executor.py
    # ------------------------------------------------------------------

    async def create_for_invocation(
        self,
        primitive: Any,
        *,
        oauth_token: str,
        instructions_text: str,
    ) -> LiveContainer:
        """F0 helper: create a fresh container per invocation.

        Writes the role instructions file, starts the container, waits
        for the entrypoint setup, and returns an un-registered
        :class:`LiveContainer`. Phase B.4's ``get_or_create`` is the
        primary path; this helper remains so the F0 executor can keep
        its one-shot semantics without wiring a lifecycle writer.
        """
        manager = self._manager_override or await asyncio.to_thread(self._build_manager)
        env = build_container_env(
            primitive,
            oauth_token=oauth_token,
            role_instructions_path=ROLE_INSTRUCTIONS_PATH,
        )
        handle = await asyncio.to_thread(
            manager.create_container,
            self._base_image_tag,
            self._workspace_volume,
            None,
            env,
        )
        await asyncio.to_thread(
            manager.write_file_to_container,
            handle,
            ROLE_INSTRUCTIONS_PATH,
            instructions_text,
        )
        await asyncio.to_thread(manager.start, handle)

        await asyncio.sleep(_ENTRYPOINT_SETUP_WAIT_SECONDS)
        await self._reload_and_verify_running(handle)

        return LiveContainer(handle=handle, manager=manager)

    async def destroy(self, live: LiveContainer) -> None:
        """F0 helper: stop (best-effort) and destroy a single container."""
        with contextlib.suppress(Exception):
            await asyncio.to_thread(live.manager.stop, live.handle, 5)
        await asyncio.to_thread(live.manager.destroy, live.handle)

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
        """Hook for primitive-specific env vars at container start time.

        Base impl returns an empty dict; Phase F.3 layers in the agent
        env (oauth token, instructions path) at turn time.
        """
        return {}

    async def _reload_and_verify_running(self, handle: Any) -> None:
        """Reload container state and assert it is running.

        No-op when the handle does not expose a real Docker container
        (e.g. test fakes) — fakes already set status on ``start()``.
        """
        inner = getattr(handle, "_container", None)
        if inner is None:
            return
        reload = getattr(inner, "reload", None)
        if reload is not None:
            await asyncio.to_thread(reload)
        status = getattr(inner, "status", None)
        if status != "running":
            logs = ""
            logs_fn = getattr(inner, "logs", None)
            if logs_fn is not None:
                try:
                    raw = logs_fn(tail=80)
                    logs = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
                except Exception:
                    logs = "<unable to read container logs>"
            failed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            raise RuntimeError(
                f"container not running after entrypoint setup "
                f"(status={status!r}, checked_at={failed_at}); "
                f"logs=\n{logs}"
            )
