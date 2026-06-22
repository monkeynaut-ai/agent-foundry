"""Run-level orchestration for construct processes.

:func:`run_process` is the single public entry point: async, full
orchestration wiring (RunContext, container registry, lifecycle writer,
signal handlers, artifacts).

Orchestration depends on the compiler (calls ``compile_process`` to
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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent_foundry.compiler.compiler import compile_process
from agent_foundry.constructs.models import get_type_args
from agent_foundry.constructs.process import Process
from agent_foundry.constructs.retry_types import (
    ResolverDidNotConvergeError,
    RetryAborted,
)
from agent_foundry.orchestration.artifacts import bootstrap_run_artifacts
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.lifecycle_writer import JsonlLifecycleWriter
from agent_foundry.orchestration.registry import AgentContainerRegistry
from agent_foundry.orchestration.run_context import (
    OnRunEndedHook,
    OnRunStartingHook,
    RunContext,
    RunEndedEvent,
    RunStartingEvent,
    current_run_context,
)
from agent_foundry.orchestration.run_outcome import (
    FailureKind,
    RunAborted,
    RunCompleted,
    RunFailed,
    RunOutcome,
)
from agent_foundry.orchestration.summary import render_summary
from agent_foundry.responders.protocol import ResponderProvider
from agent_foundry.telemetry import setup as telemetry_setup
from agent_foundry.telemetry.config import TelemetryConfig

logger = logging.getLogger(__name__)


def _safe_invoke_hooks(
    hooks: list[Callable[[Any], None]],
    event: Any,
    *,
    label: str,
) -> None:
    """Invoke each hook in order with the given event payload; isolate
    exceptions, log, continue.

    Iterates the live list (not a snapshot) so a hook may register
    additional hooks during execution and have them run in the same
    pass. The MLflow adapter relies on this: an on_run_starting hook
    calls ``enable()`` which appends MLflow on_run_ended hooks to the
    same list.

    Catches BaseException to isolate one hook's failure from another.
    Hooks must be synchronous and must not re-raise BaseException
    subclasses that should propagate to the runner.
    """
    for hook in hooks:
        try:
            hook(event)
        except BaseException:
            logger.exception("RunContext %s hook raised; continuing", label)


async def run_process(
    process: Process,
    *,
    initial_state: BaseModel,
    artifacts_dir: Path,
    workspace_volume: str,
    base_image_tag: str,
    responder_provider: ResponderProvider,
    run_id: str | None = None,
    on_run_starting: list[OnRunStartingHook] | None = None,
    on_run_ended: list[OnRunEndedHook] | None = None,
    telemetry: TelemetryConfig | None = None,
    extra_env: dict[str, str] | None = None,
    extra_volumes: dict[str, dict[str, str]] | None = None,
) -> RunOutcome:
    """Execute a :class:`Process` with full orchestration wiring.

    Bootstraps the run artifacts directory, builds a
    :class:`JsonlLifecycleWriter` and :class:`AgentContainerRegistry`,
    constructs the :class:`RunContext`, installs cooperative
    SIGINT/SIGTERM handlers (main thread only), sets the
    ``current_run_context`` ContextVar, invokes any supplied
    ``on_run_starting`` hooks (each receiving a :class:`RunStartingEvent`),
    and invokes the compiled graph via :meth:`ainvoke`.

    Returns exactly one :class:`RunOutcome` and never re-raises an
    in-graph exception. The body's four terminal conditions classify as:
    a clean graph return → ``RunCompleted``; a ``RetryAborted`` →
    ``RunAborted``; a ``ResolverDidNotConvergeError`` →
    ``RunFailed(BACKSTOP)``; any other ``BaseException`` →
    ``RunFailed(CRASH)``. Exceptions raised before the graph runs (e.g.
    telemetry setup) still propagate.

    Teardown (``finally``) always runs: writes exactly ONE terminal
    lifecycle event (``RUN_ENDED`` / ``RUN_ABORTED`` / ``RUN_FAILED`` per
    outcome, with ``error_kind`` on the ``RUN_FAILED`` record), shuts down
    the registry, renders ``summary.txt``, invokes ``on_run_ended`` hooks
    (each receiving a :class:`RunEndedEvent` carrying the context, the
    typed outcome, the captured exception or None, and the final output
    model or None), then resets the ContextVar and signal handlers — even
    on cancel or agent failure.
    """
    resolved_run_id = run_id if run_id is not None else uuid.uuid4().hex

    run_dir = bootstrap_run_artifacts(
        artifacts_dir=artifacts_dir,
        run_id=resolved_run_id,
        workspace_volume=workspace_volume,
        base_image_tag=base_image_tag,
    )

    # Build the per-run TracerProvider BEFORE constructing RunContext so
    # the context can carry it. NEVER call ``trace.set_tracer_provider``;
    # provider isolation is per-run, anchored on the context. If the
    # constructor raises (e.g. bad endpoint URL fails OTLPSpanExporter
    # init), clean up the already-bootstrapped run_dir before propagating
    # so failed runs don't leak directories on disk.
    telemetry_provider = None
    if telemetry is not None:
        try:
            telemetry_provider = telemetry_setup.build_tracer_provider(telemetry)
        except Exception:
            import shutil as _shutil

            _shutil.rmtree(run_dir, ignore_errors=True)
            raise

    _, root_out = get_type_args(process.root)

    lifecycle = JsonlLifecycleWriter(run_id=resolved_run_id, path=run_dir / "lifecycle.jsonl")

    oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    registry = AgentContainerRegistry(
        workspace_volume=workspace_volume,
        base_image_tag=base_image_tag,
        oauth_token=oauth_token,
    )
    cancel = asyncio.Event()

    run_ctx = RunContext(
        run_id=resolved_run_id,
        artifacts_dir=run_dir,
        container_registry=registry,
        responder_provider=responder_provider,
        lifecycle_writer=lifecycle,
        cancel_event=cancel,
        env={"CLAUDE_CODE_OAUTH_TOKEN": oauth_token} if oauth_token else {},
        extra_env=extra_env,
        extra_volumes=extra_volumes,
        on_run_starting=list(on_run_starting or []),
        on_run_ended=list(on_run_ended or []),
        telemetry=telemetry,
        telemetry_provider=telemetry_provider,
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
    _safe_invoke_hooks(
        run_ctx.on_run_starting,
        RunStartingEvent(run_context=run_ctx),
        label="on_run_starting",
    )

    caught_exc: BaseException | None = None
    final_output: BaseModel | None = None
    outcome: RunOutcome
    # Clause ordering is load-bearing: RetryAborted and
    # ResolverDidNotConvergeError must precede the broad except BaseException,
    # else they fall into the CRASH path.
    try:
        graph = compile_process(process)
        result_dict = await graph.ainvoke(initial_state.model_dump())
        final_output = root_out.model_validate(result_dict)
        outcome = RunCompleted(output=final_output)
    except RetryAborted as aborted:
        outcome = RunAborted(reason=aborted.reason)
    except ResolverDidNotConvergeError as backstop:
        caught_exc = backstop
        outcome = RunFailed(
            error_kind=FailureKind.BACKSTOP,
            error_type=type(backstop).__name__,
            message=str(backstop),
        )
    except BaseException as exc:
        caught_exc = exc
        outcome = RunFailed(
            error_kind=FailureKind.CRASH,
            error_type=type(exc).__name__,
            message=str(exc),
        )
    finally:
        # Order matters:
        #   1. Write the terminal lifecycle event so the JSONL stream has
        #      a terminal record before downstream consumers (render_summary,
        #      on_close hooks) read it. error_kind rides the RUN_FAILED record
        #      so render_summary reads one field.
        if isinstance(outcome, RunAborted):
            terminal = LifecycleEvent.RUN_ABORTED
        elif isinstance(outcome, RunFailed):
            terminal = LifecycleEvent.RUN_FAILED
        else:
            terminal = LifecycleEvent.RUN_ENDED
        extra_fields = (
            {"error_kind": outcome.error_kind.value} if isinstance(outcome, RunFailed) else {}
        )
        lifecycle.append(terminal, run_id=resolved_run_id, **extra_fields)
        #   2. Existing teardown that produces files in artifacts_dir
        #      (registry.shutdown_all, render_summary). Each remains in
        #      its own try/except so a teardown failure can't prevent
        #      on_close from firing.
        try:
            await registry.shutdown_all(pause_on_failure=run_ctx.pause_on_failure)
        except Exception:
            logger.warning("registry.shutdown_all raised during teardown", exc_info=True)
        try:
            render_summary(run_dir)
        except Exception:
            logger.warning("render_summary raised during teardown", exc_info=True)
        #   3. on_run_ended hooks fire AFTER render_summary. This lets a
        #      product's ArtifactSpec entries reference summary.txt and
        #      anything else render_summary writes.
        _safe_invoke_hooks(
            run_ctx.on_run_ended,
            RunEndedEvent(
                run_context=run_ctx,
                exception=caught_exc,
                output=final_output,
                outcome=outcome,
            ),
            label="on_run_ended",
        )
        #   4. ContextVar reset, signal handler removal, lifecycle.close,
        #      and per-run TracerProvider shutdown. Wrap shutdown in
        #      try/except so a hung exporter or unreachable backend
        #      can't mask the original run exception.
        for sig in installed_signals:
            with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                loop.remove_signal_handler(sig)
        current_run_context.reset(token)
        lifecycle.close()
        if telemetry_provider is not None:
            try:
                telemetry_provider.shutdown()
            except Exception:
                logger.warning(
                    "TracerProvider.shutdown raised during teardown",
                    exc_info=True,
                )

    # Placed after try/finally so the finally block runs exactly once before
    # every terminal path returns its classified envelope.
    return outcome
