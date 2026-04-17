"""Run-level orchestration for primitive plans.

Two entry points:

  * :func:`run_primitive_plan` — async, full orchestration wiring
    (AgentRunContext, container registry, lifecycle writer, signal
    handlers, artifacts). The primary public entry point.

  * :func:`run_primitive_plan_sync` — legacy synchronous entry.
    Useful for plans with no ``AgentAction`` (no containers); emits a
    ``DeprecationWarning`` nudging toward the async entry.

Orchestration depends on the compiler (calls ``_compile_primitive`` to
build the executable graph), not the other way around. The compiler
knows nothing about runs, contexts, responders, or containers.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import threading
import uuid
import warnings
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent_foundry.compiler.primitive_compiler import _compile_primitive
from agent_foundry.orchestration.artifacts import bootstrap_run_artifacts
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.lifecycle_writer import JsonlLifecycleWriter
from agent_foundry.orchestration.registry import AgentContainerRegistry
from agent_foundry.orchestration.run_context import (
    AgentRunContext,
    current_run_context,
)
from agent_foundry.orchestration.summary import render_summary
from agent_foundry.primitives.models import get_type_args
from agent_foundry.primitives.plan import PrimitivePlan
from agent_foundry.responders.protocol import ResponderProvider

logger = logging.getLogger(__name__)


def run_primitive_plan_sync(
    plan: PrimitivePlan,
    initial_state: BaseModel | None = None,
    config: dict[str, Any] | None = None,
) -> BaseModel:
    """Legacy synchronous entry point.

    Preserved for call sites that do not build an
    :class:`AgentRunContext`. Emits a ``DeprecationWarning``; prefer the
    async :func:`run_primitive_plan` which builds the context and wires
    lifecycle + registry teardown.
    """
    warnings.warn(
        "run_primitive_plan_sync is deprecated; migrate to the async "
        "run_primitive_plan entry point.",
        DeprecationWarning,
        stacklevel=2,
    )
    _, root_out = get_type_args(plan.root)
    graph = _compile_primitive(plan)

    input_dict = initial_state.model_dump() if initial_state is not None else {}
    result_dict = graph.invoke(input_dict, config=config or {})
    return root_out.model_validate(result_dict)


async def run_primitive_plan(
    plan: PrimitivePlan,
    *,
    initial_state: BaseModel,
    artifacts_dir: Path,
    workspace_volume: str,
    base_image_tag: str,
    responder_provider: ResponderProvider,
    run_id: str | None = None,
) -> BaseModel:
    """Execute a :class:`PrimitivePlan` with full orchestration wiring.

    Bootstraps the run artifacts directory, builds a
    :class:`JsonlLifecycleWriter` and :class:`AgentContainerRegistry`,
    constructs the :class:`AgentRunContext`, installs cooperative
    SIGINT/SIGTERM handlers (main thread only), sets the
    ``current_run_context`` ContextVar, and invokes the compiled graph
    via :meth:`ainvoke`.

    Teardown (``finally``) always runs: the registry is shut down,
    ``summary.txt`` is rendered, and the ContextVar + signal handlers
    are reset — even on cancel or agent failure.
    """
    resolved_run_id = run_id if run_id is not None else uuid.uuid4().hex

    run_dir = bootstrap_run_artifacts(
        artifacts_dir=artifacts_dir,
        run_id=resolved_run_id,
        workspace_volume=workspace_volume,
        base_image_tag=base_image_tag,
    )

    _, root_out = get_type_args(plan.root)

    lifecycle = JsonlLifecycleWriter(run_id=resolved_run_id, path=run_dir / "lifecycle.jsonl")

    oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    # Inject role instructions + wait for container health only when we
    # have a real OAuth token — unit tests that wire a fake driver skip
    # this path and keep their minimal registry shape. The base image
    # declares a HEALTHCHECK that polls for ``/tmp/.container-ready``;
    # the entrypoint touches that marker after all setup completes.
    registry = AgentContainerRegistry(
        workspace_volume=workspace_volume,
        base_image_tag=base_image_tag,
        oauth_token=oauth_token,
        inject_instructions=oauth_token is not None,
        wait_for_health=oauth_token is not None,
    )
    cancel = asyncio.Event()

    run_ctx = AgentRunContext(
        run_id=resolved_run_id,
        artifacts_dir=run_dir,
        container_registry=registry,
        responder_provider=responder_provider,
        lifecycle_writer=lifecycle,
        cancel_event=cancel,
        env={"CLAUDE_CODE_OAUTH_TOKEN": oauth_token} if oauth_token else {},
    )

    # Install SIGINT/SIGTERM handlers — main thread only. Signal-handler
    # installation from a non-main thread raises ``ValueError`` on
    # POSIX; guard explicitly so we degrade cleanly in worker threads
    # (tests, notebook kernels) rather than crashing the run.
    loop = asyncio.get_running_loop()
    installed_signals: list[int] = []
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, cancel.set)
                installed_signals.append(sig)
            except (NotImplementedError, RuntimeError, ValueError):
                # NotImplementedError on Windows; RuntimeError/ValueError
                # on loops that refuse signal handlers (uvloop edge
                # cases, nested loops). Cancellation still works via
                # direct ``cancel_event.set()`` from callers.
                pass

    token = current_run_context.set(run_ctx)
    lifecycle.append(LifecycleEvent.RUN_STARTED, run_id=resolved_run_id)

    try:
        graph = _compile_primitive(plan)
        result_dict = await graph.ainvoke(initial_state.model_dump())
        lifecycle.append(LifecycleEvent.RUN_ENDED, run_id=resolved_run_id)
        return root_out.model_validate(result_dict)
    finally:
        try:
            await registry.shutdown_all()
        except Exception:
            logger.warning("registry.shutdown_all raised during teardown", exc_info=True)
        try:
            render_summary(run_dir)
        except Exception:
            logger.warning("render_summary raised during teardown", exc_info=True)
        for sig in installed_signals:
            with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                loop.remove_signal_handler(sig)
        current_run_context.reset(token)
        lifecycle.close()
