"""RunContext — the per-plan-execution context carried through compiled plans.

Constructed once at plan start (in ``run_primitive_plan``) before the compiled
graph runs and remains active through every primitive (Sequence, Loop,
AgentAction, FunctionAction, …). Carries plan-level state: ``run_id``,
``artifacts_dir``, ``lifecycle_writer``, ``cancel_event``, container
registry, responder provider, env.

Module-level ``current_run_context`` ContextVar + ``require_current_run_context``
helper expose the active context to compiled nodes and to product code via
``agent_foundry.runtime`` accessors.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from pydantic import BaseModel, ConfigDict, Field

from agent_foundry.orchestration.lifecycle_writer import (
    LifecycleWriter,
    NoOpLifecycleWriter,
)
from agent_foundry.telemetry.config import TelemetryConfig

__all__ = [
    "LifecycleWriter",
    "NoOpLifecycleWriter",
    "OnRunEndedHook",
    "OnRunStartingHook",
    "RunContext",
    "RunEndedEvent",
    "RunStartingEvent",
    "current_run_context",
    "require_current_run_context",
]


def _read_pause_on_failure_env() -> bool:
    """Read ``AGENT_FOUNDRY_PAUSE_ON_FAILURE`` and parse it as a bool.

    Default behavior is to retain failed containers (True), matching the
    "retain forensic state, require manual cleanup" stance the codebase
    already takes for workspace volumes. The env var lets ad-hoc runs
    opt OUT — ``0`` / ``false`` / ``no`` (case-insensitive) returns
    False, anything else (including unset) returns True.
    """
    val = os.environ.get("AGENT_FOUNDRY_PAUSE_ON_FAILURE", "").strip().lower()
    return val not in {"0", "false", "no"}


def _default_artifacts_dir() -> Path:
    """Produce an ephemeral artifacts directory when none is given.

    Each construction gets a unique path under ``<cwd>/.tmp/`` so tests
    and ad-hoc uses can't accidentally write into the current working
    directory itself, and so leaked dirs stay scoped to the project
    rather than scattered across the system tmp. ``.tmp/`` is gitignored
    by convention in this repo (and consumers should add it to their
    own ``.gitignore``). Production code (``run_primitive_plan``) always
    supplies an explicit ``artifacts_dir``.
    """
    parent = Path.cwd() / ".tmp"
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="agent_foundry_run_", dir=str(parent)))


class RunContext(BaseModel):
    """Per-plan-execution context threaded through compiled plan execution.

    Fields:
      - ``run_id``: unique identifier for this run (non-empty)
      - ``artifacts_dir``: directory for per-run artifacts
      - ``container_registry``: AgentContainerRegistry (duck-typed)
      - ``responder_provider``: resolves ``responder_id`` -> responder callable
      - ``lifecycle_writer``: a concrete :class:`LifecycleWriter` subclass
      - ``cancel_event``: cooperative cancellation signal. ``frozen=True`` blocks
        reassignment but callers may still mutate the event (``cancel_event.set()``).
      - ``env``: container env dict (must include CLAUDE_CODE_OAUTH_TOKEN)
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    run_id: str = Field(min_length=1)
    # ``artifacts_dir``, ``responder_provider``, and ``cancel_event`` ship
    # with defaults so minimal call sites (and their tests) continue to
    # work; real construction sites (``run_primitive_plan``) pass
    # explicit values for all three.
    artifacts_dir: Path = Field(default_factory=_default_artifacts_dir)
    container_registry: Any
    responder_provider: Any = None
    lifecycle_writer: LifecycleWriter
    cancel_event: asyncio.Event = Field(default_factory=asyncio.Event)
    env: dict[str, str]

    pause_on_failure: bool = Field(default_factory=_read_pause_on_failure_env)
    """If true, the agent container that produced a failure is not torn
    down at the end of the run. Default sourced from
    ``AGENT_FOUNDRY_PAUSE_ON_FAILURE`` (0/false/no → False, anything
    else → True).
    """

    on_run_starting: list[Callable[[RunStartingEvent], None]] = Field(default_factory=list)
    """Hooks invoked while the run is in the act of starting.

    Fires after the ``RunContext`` is constructed and bound to the
    ``current_run_context`` ContextVar, after the lifecycle stream has
    emitted ``RUN_STARTED``, after the per-run TracerProvider (if any) is
    anchored on the context — and immediately before the compiled graph
    is invoked. Hooks are the last step of the starting sequence.

    Each hook receives a :class:`RunStartingEvent`. Hook exceptions are
    caught, logged, and do not block other hooks or the run itself.

    Mutation contract: append to this list
    (``ctx.on_run_starting.append(hook)``); do NOT reassign the field
    (``ctx.on_run_starting = [...]`` raises ValidationError because
    RunContext has ``frozen=True``).

    Iteration semantics: the runner iterates this list with a live
    reference (``for hook in ctx.on_run_starting``), not a snapshot.
    This means a hook may append additional hooks during execution and
    they will run in the same pass. The MLflow adapter relies on this
    to register on_run_ended hooks from within an on_run_starting
    hook. Do not change this iteration to a snapshot
    (``for hook in list(ctx.on_run_starting)``) without auditing all
    callers.
    """

    on_run_ended: list[Callable[[RunEndedEvent], None]] = Field(default_factory=list)
    """Hooks invoked after the run has ended.

    Fires after the graph has finished or raised, after the terminal
    lifecycle event (``RUN_ENDED`` on success or ``RUN_FAILED`` on
    exception) has been written, after the container registry has shut
    down, and after ``render_summary`` has written ``summary.txt`` —
    but before the final cleanup steps (ContextVar reset, signal
    handler removal, ``lifecycle.close()``, TracerProvider shutdown).

    Each hook receives a :class:`RunEndedEvent` carrying the context,
    the captured exception (or ``None`` on success), and the run's
    final output model (or ``None`` on failure). Hook exceptions are
    caught, logged, and do not block other hooks or final teardown.

    Same mutation contract and iteration semantics as
    ``on_run_starting``.
    """

    telemetry: TelemetryConfig | None = None
    """Active telemetry config for this run, or None if telemetry is disabled.
    Read by compiler nodes to find redaction policy and run-id binding.
    """

    telemetry_provider: SDKTracerProvider | None = None
    """Per-run OTel TracerProvider, or None if telemetry is disabled.

    Per-run isolation: each ``run_primitive_plan`` invocation builds its own
    provider and stores it here. ``emit_span`` resolves the active
    ``RunContext.telemetry_provider`` via the ContextVar — no process-global
    tracer-provider state is touched. This is what makes concurrent runs in
    the same process safe.
    """


class RunStartingEvent(BaseModel):
    """Payload delivered to ``on_run_starting`` hooks.

    Fires when the run is in the act of starting: the ``RunContext`` is
    constructed and bound to the ``current_run_context`` ContextVar, the
    lifecycle stream has emitted ``RUN_STARTED``, the telemetry provider
    (if any) is anchored on the context — but the compiled graph has not
    yet been invoked. Hooks fire as the last step of the starting
    sequence; immediately after they return, ``graph.ainvoke`` runs.

    Use this hook to register per-run integrations (MLflow Run start,
    custom dashboards, span enrichment) that need an active
    ``RunContext`` to bind against. Output and exception are unavailable
    here by definition — they belong to ``RunEndedEvent``.

    Forward-compatible: new fields can be added without breaking
    existing hooks. Read fields by name (``event.run_context``).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    run_context: RunContext


class RunEndedEvent(BaseModel):
    """Payload delivered to ``on_run_ended`` hooks.

    Fires after the run has completed (success or failure). By the time
    a hook receives this event:

    - The graph has finished or raised.
    - ``final_output`` has been validated, or an exception captured.
    - The terminal lifecycle event (``RUN_ENDED`` on success or
      ``RUN_FAILED`` on exception) has been written.
    - The container registry has shut down its agents.
    - ``render_summary`` has written ``summary.txt``.

    Hooks fire BEFORE the very last cleanup steps (ContextVar reset,
    signal handler removal, ``lifecycle.close()``, TracerProvider
    shutdown). The ``RunContext`` is still bound at this point.

    The two nullable fields together encode the run's terminal state:

    +----------------+-----------------+----------------+
    | exception      | output          | meaning        |
    +================+=================+================+
    | ``None``       | a ``BaseModel`` | clean success  |
    +----------------+-----------------+----------------+
    | exception inst | ``None``        | failure        |
    +----------------+-----------------+----------------+

    Forward-compatible: new fields can be added without breaking
    existing hooks. Read fields by name (``event.exception``,
    ``event.output``) so the meaning is never ambiguous.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    run_context: RunContext
    exception: BaseException | None = None
    output: BaseModel | None = None


OnRunStartingHook = Callable[[RunStartingEvent], None]
"""Hook signature for ``RunContext.on_run_starting``.

Receives a :class:`RunStartingEvent`; returns ``None``. Hook exceptions
are caught and logged by the runner — they do not block other hooks or
the run itself. Hooks must be synchronous.
"""

OnRunEndedHook = Callable[[RunEndedEvent], None]
"""Hook signature for ``RunContext.on_run_ended``.

Receives a :class:`RunEndedEvent`; returns ``None``. Hook exceptions
are caught and logged by the runner — they do not block other hooks or
final teardown. Hooks must be synchronous.
"""


current_run_context: ContextVar[RunContext | None] = ContextVar("current_run_context", default=None)
"""Thread-/task-local pointer to the active ``RunContext``.

Compiled nodes read this at invocation time to resolve the active run
context without having to close over it at compile time. Product code
inside a ``FunctionAction`` callable reaches it indirectly through
``agent_foundry.runtime`` accessors.
"""


def require_current_run_context() -> RunContext:
    """Return the active ``RunContext`` or raise ``RuntimeError``."""
    ctx = current_run_context.get()
    if ctx is None:
        raise RuntimeError(
            "No active RunContext: current_run_context ContextVar is unset. "
            "A compiled node tried to access run context outside a run."
        )
    return ctx
