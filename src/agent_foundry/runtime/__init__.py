"""Runtime accessors for product code inside a running AgentAction / FunctionAction.

Inside a running plan, product code can call these helpers to read or
write run-scoped state without having to thread ``RunContext``
through every function signature. The accessors resolve the active
run context from the ``current_run_context`` ContextVar that the
compiler sets for every compiled node.

Outside a run, every accessor returns a safe default (``None`` /
``False`` / no-op) rather than raising — so product code that might
run both inside and outside a plan doesn't need special-case branches.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_foundry.orchestration.run_context import current_run_context

if TYPE_CHECKING:
    from agent_foundry.responders.protocol import Responder


def emit(kind: str, **fields: Any) -> None:
    """Emit a product-defined lifecycle event.

    Wire shape: a ``type="domain"`` record with the product-chosen
    ``kind`` subtype and free-form fields. Downstream consumers
    (summary renderers, dashboards) filter by ``type == "domain"``
    and route on ``kind``.

    No-op if called outside a run.
    """
    ctx = current_run_context.get()
    if ctx is not None:
        ctx.lifecycle_writer.append_run_event(kind, **fields)


def run_id() -> str | None:
    """Return the current run's id, or ``None`` outside a run."""
    ctx = current_run_context.get()
    return ctx.run_id if ctx is not None else None


def artifacts_dir() -> Path | None:
    """Return the current run's artifacts directory, or ``None`` outside a run."""
    ctx = current_run_context.get()
    return ctx.artifacts_dir if ctx is not None else None


def cancelled() -> bool:
    """Return True if the current run has been cancelled via ``cancel_event``.

    Returns ``False`` outside a run.
    """
    ctx = current_run_context.get()
    if ctx is None:
        return False
    return ctx.cancel_event.is_set()


def responder() -> Responder | None:
    """Return the run's resolved operator responder, or ``None``.

    Returns ``None`` outside a run, and ``None`` when the active run was
    started without a responder provider. Inside a run with a provider,
    resolves and returns the ``Responder`` so async product code can
    ``await responder().respond(request, context)``.
    """
    ctx = current_run_context.get()
    if ctx is None:
        return None
    provider = ctx.responder_provider
    if provider is None:
        return None
    return provider()


__all__ = ["artifacts_dir", "cancelled", "emit", "responder", "run_id"]
