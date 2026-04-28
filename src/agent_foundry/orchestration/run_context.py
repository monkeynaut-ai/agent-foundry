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
import tempfile
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_foundry.orchestration.lifecycle_writer import (
    LifecycleWriter,
    NoOpLifecycleWriter,
)

__all__ = [
    "LifecycleWriter",
    "NoOpLifecycleWriter",
    "RunContext",
    "current_run_context",
    "require_current_run_context",
]


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

    on_open: list[Callable[[RunContext], None]] = Field(default_factory=list)
    """Callables invoked once the RunContext is constructed and the
    ``current_run_context`` ContextVar is set, before the compiled graph runs.
    Each hook receives the context. Hook exceptions are caught, logged, and
    do not block other hooks or the run itself.

    Mutation contract: append to this list (``ctx.on_open.append(hook)``); do
    NOT reassign the field (``ctx.on_open = [...]`` raises ValidationError
    because RunContext has ``frozen=True``).

    Iteration semantics: the runner iterates this list with a live reference
    (``for hook in ctx.on_open``), not a snapshot. This means a hook may
    append additional hooks during execution and they will run in the same
    pass. The MLflow adapter relies on this to register lifecycle hooks from
    within an on_open hook. Do not change this iteration to a snapshot
    (``for hook in list(ctx.on_open)``) without auditing all callers.
    """

    on_close: list[Callable[[RunContext, BaseException | None, BaseModel | None], None]] = Field(
        default_factory=list
    )
    """Callables invoked when the run is exiting, before teardown. Receives:
      - the context
      - the exception (or None on success)
      - the run's final output BaseModel (or None on failure / before output materialises)

    Hook exceptions are caught, logged, and do not block other hooks or
    teardown.

    Same mutation contract and iteration semantics as ``on_open``.
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
