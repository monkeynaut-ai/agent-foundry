"""Minimal AgentContainerRegistry (F0).

F0 mode: every create_for_invocation creates a brand-new container,
writes the instruction file, starts it, and returns a LiveContainer.
Phase B Task B.4 extends with reuse-policy-aware get_or_create.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass
from typing import Any

from agent_foundry.orchestration.env import build_container_env

ROLE_INSTRUCTIONS_PATH = "/home/claude/role-instructions.md"
_ENTRYPOINT_SETUP_WAIT_SECONDS = 2.0


@dataclass
class LiveContainer:
    handle: Any
    manager: Any
    session_id: str | None = None


class AgentContainerRegistry:
    """F0 registry — no reuse, no keying, no session recording.

    Phase B.4 replaces create_for_invocation with a policy-aware
    get_or_create and adds record_session_id / shutdown_all.
    """

    def __init__(
        self,
        *,
        manager: Any,
        base_image_tag: str,
        workspace_volume: str,
    ) -> None:
        self._manager = manager
        self._base_image_tag = base_image_tag
        self._workspace_volume = workspace_volume

    async def create_for_invocation(
        self,
        primitive: Any,
        *,
        oauth_token: str,
        instructions_text: str,
    ) -> LiveContainer:
        env = build_container_env(
            primitive,
            oauth_token=oauth_token,
            role_instructions_path=ROLE_INSTRUCTIONS_PATH,
        )
        handle = await asyncio.to_thread(
            self._manager.create_container,
            image=self._base_image_tag,
            workspace_volume=self._workspace_volume,
            extra_env=env,
        )
        await asyncio.to_thread(
            self._manager.write_file_to_container,
            handle,
            ROLE_INSTRUCTIONS_PATH,
            instructions_text,
        )
        await asyncio.to_thread(self._manager.start, handle)

        # Readiness wait: the entrypoint performs ~2s of setup (plugin
        # install, role-instructions append) before the container reaches
        # its `tail -f /dev/null` idle state. Phase 0's smoke test proves
        # this fixed sleep + status check is sufficient. A proper
        # poll-based readiness check can come in a later phase.
        await asyncio.sleep(_ENTRYPOINT_SETUP_WAIT_SECONDS)
        await self._reload_and_verify_running(handle)

        return LiveContainer(handle=handle, manager=self._manager)

    async def destroy(self, live: LiveContainer) -> None:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self._manager.stop, live.handle, 5)
        await asyncio.to_thread(self._manager.destroy, live.handle)

    async def _reload_and_verify_running(self, handle: Any) -> None:
        """Reload the container state and assert it is running.

        No-op when the handle does not expose a real Docker container
        (e.g. test fakes) — fakes already set status on start().
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
            # Best-effort stamp so callers can see when the readiness
            # check failed relative to entrypoint setup.
            failed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            raise RuntimeError(
                f"container not running after entrypoint setup "
                f"(status={status!r}, checked_at={failed_at}); "
                f"logs=\n{logs}"
            )
