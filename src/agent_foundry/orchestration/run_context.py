"""AgentRunContext — the per-run context carried through compiled plans.

CS7 Plan 2 Task B.1 expands the context with:
  - ``artifacts_dir``: per-run artifacts directory
  - ``responder_provider``: typed as ``Any`` until Task C.2 introduces
    the ``ResponderProvider`` protocol.
  - ``cancel_event``: cooperative cancellation signal
  - module-level ``current_run_context`` ContextVar + a
    ``require_current_run_context`` helper used by compiled nodes
    (wiring lands in Task G.1).
"""

from __future__ import annotations

import asyncio
import tempfile
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


def _default_artifacts_dir() -> Path:
    """Produce an ephemeral tmp directory for artifacts when none is given.

    Each construction gets a unique path under the system tmp so tests
    and ad-hoc uses can't accidentally write into the current working
    directory. Production code (``run_primitive_plan``) always supplies
    an explicit ``artifacts_dir``.
    """
    return Path(tempfile.mkdtemp(prefix="agent_foundry_run_"))


class LifecycleWriter(Protocol):
    def append(self, event: dict[str, Any]) -> None: ...


class NoOpLifecycleWriter:
    """Satisfies the LifecycleWriter protocol by discarding all events.

    Phase B Task B.2 introduces the real append-only jsonl writer.
    """

    def append(self, event: dict[str, Any]) -> None:
        return None


class AgentRunContext(BaseModel):
    """Per-run context threaded through compiled plan execution.

    Fields:
      - ``run_id``: unique identifier for this run (non-empty)
      - ``artifacts_dir``: directory for per-run artifacts
      - ``container_registry``: AgentContainerRegistry (duck-typed)
      - ``responder_provider``: resolves ``responder_id`` -> responder
        callable. Typed as ``Any`` until Task C.2 lands the
        ``ResponderProvider`` protocol.
      - ``lifecycle_writer``: any object satisfying LifecycleWriter
      - ``cancel_event``: cooperative cancellation signal. ``frozen=True``
        blocks reassignment but callers may still mutate the event
        (``cancel_event.set()``).
      - ``env``: container env dict (must include CLAUDE_CODE_OAUTH_TOKEN)
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    run_id: str = Field(min_length=1)
    # ``artifacts_dir``, ``responder_provider``, and ``cancel_event`` ship
    # with defaults so F0 call sites (and their tests) continue to work
    # unchanged; Task C-series and G.1 replace these with explicit values
    # at every real construction site.
    artifacts_dir: Path = Field(default_factory=_default_artifacts_dir)
    container_registry: Any
    responder_provider: Any = None
    lifecycle_writer: Any
    cancel_event: asyncio.Event = Field(default_factory=asyncio.Event)
    env: dict[str, str]


current_run_context: ContextVar[AgentRunContext | None] = ContextVar(
    "current_run_context", default=None
)
"""Thread-/task-local pointer to the active ``AgentRunContext``.

Compiled nodes read this at invocation time (Task G.1) to thread the
run context into two-arg ``FunctionAction`` callables without having
to close over it at compile time.
"""


def require_current_run_context() -> AgentRunContext:
    """Return the active ``AgentRunContext`` or raise ``RuntimeError``.

    Used by compiled nodes that need run-scoped context (responders,
    cancel event, artifacts dir). Raising here surfaces a clear
    "no run in progress" message rather than an ``AttributeError``
    three frames deep.
    """
    ctx = current_run_context.get()
    if ctx is None:
        raise RuntimeError(
            "No active AgentRunContext: current_run_context ContextVar is unset. "
            "A compiled node tried to access run context outside a run."
        )
    return ctx
