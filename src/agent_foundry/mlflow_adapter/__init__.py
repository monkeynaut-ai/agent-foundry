"""MLflow adapter for Agent Foundry telemetry.

Provides:
  - ``MLFLOW_TRANSLATIONS``: attribute-translation table products plug into
    ``TelemetryConfig.attribute_translations`` to mirror AF span attributes
    under MLflow names. Translation happens at emit time, not as a
    SpanProcessor.
  - ``enable(config, run_context, input_model, *, tracking_uri,
    experiment_id)``: configures the MLflow client and attaches Run
    start/end hooks to ``run_context.on_open`` / ``on_close``.

Optional install — requires the ``[mlflow]`` extra:

    pip install agent-foundry[mlflow]
"""

from __future__ import annotations

import threading
import weakref

from pydantic import BaseModel

# Import-guard (raises actionable ImportError if mlflow isn't installed).
# We do NOT add ``import mlflow`` at module top: the ruff formatter would
# reorder it above ``extras``, and a missing-mlflow scenario would surface
# the generic Python ImportError instead of our actionable message. The
# adapter-side ``import mlflow`` therefore lives inside ``enable()``.
from agent_foundry.mlflow_adapter import extras  # noqa: F401
from agent_foundry.mlflow_adapter.run_lifecycle import attach_run_hooks
from agent_foundry.mlflow_adapter.translation import MLFLOW_TRANSLATIONS
from agent_foundry.orchestration.run_context import RunContext
from agent_foundry.telemetry.config import TelemetryConfig

# Idempotency tracking, keyed on RunContext object identity (via id()).
#
# We deliberately do NOT use ``weakref.WeakSet`` here: WeakSet uses
# ``__hash__`` / ``__eq__`` for membership, and Pydantic frozen models hash
# by field values — two distinct RunContext instances with all the same
# field values would collide. Object identity is what we want.
#
# Stale ``id()`` entries are pruned when the RunContext is garbage-collected
# via ``weakref.finalize``, so the set never accumulates stale state in
# long-running processes.
_ENABLED_CONTEXT_IDS: set[int] = set()
_ENABLED_CONTEXTS_LOCK = threading.Lock()


def reset_for_testing() -> None:
    """Clear the idempotency-tracking set. Tests call this in fixtures so
    contexts created in earlier tests don't suppress registration in later
    tests. Not part of the production surface — finalize handles real
    RunContext lifetimes automatically.
    """
    with _ENABLED_CONTEXTS_LOCK:
        _ENABLED_CONTEXT_IDS.clear()


def _unregister(ctx_id: int) -> None:
    """Remove a context id from the enabled set. Called by weakref.finalize
    when the RunContext is garbage-collected, preventing id() reuse hazards.
    """
    with _ENABLED_CONTEXTS_LOCK:
        _ENABLED_CONTEXT_IDS.discard(ctx_id)


def enable(
    *,
    config: TelemetryConfig,
    run_context: RunContext,
    input_model: BaseModel,
    tracking_uri: str | None = None,
    experiment_id: str | None = None,
) -> None:
    """Wire the MLflow adapter into a per-run telemetry pipeline.

    Two sides of the integration share an experiment but are configured
    separately because they target different APIs:

    - **Trace spans** flow over OTLP/HTTP. Routing to a specific MLflow
      experiment uses the ``x-mlflow-experiment-id`` header; the product
      sets that on ``config.otlp_headers`` BEFORE calling
      ``run_primitive_plan`` (the runner builds the OTLP exporter at that
      point, so post-build mutations don't reach it).
    - **Run data** (params, metrics, tags, artifacts via ``mlflow.log_*``)
      uses the ``mlflow`` client library's global state. ``enable()`` sets
      that state for the caller — pass ``tracking_uri`` to point the client
      at the MLflow server and ``experiment_id`` to route logged Runs.

    Pass both ``tracking_uri`` and ``experiment_id`` (or neither — if you've
    set ``MLFLOW_TRACKING_URI`` / ``MLFLOW_EXPERIMENT_ID`` env vars the
    client picks them up automatically and you can leave these args
    unset). Setting one without the other is allowed but uncommon.

    **Ordering constraint**: must be called from a ``run_context.on_open``
    hook (or any callsite that runs after ``run_primitive_plan`` has built
    a ``TracerProvider`` and anchored it on
    ``run_context.telemetry_provider``). Calling at process startup, before
    ``run_primitive_plan``, raises ``RuntimeError`` because no per-run
    provider exists yet.

    Idempotent within a process: registering the same ``run_context`` twice
    is a no-op. Different ``run_context`` instances always get their own
    hooks, even if they share a ``run_id``. Thread-safe: concurrent calls
    on the same context are serialised so that exactly one set of hooks is
    attached.

    Note: this function does NOT register a SpanProcessor. Attribute
    translation happens at emit time via
    ``TelemetryConfig.attribute_translations`` (set by the product to
    ``MLFLOW_TRANSLATIONS`` exported from this module). MLflow client
    config and Run lifecycle hooks are the only side effects.
    """
    import mlflow

    provider = run_context.telemetry_provider
    if provider is None:
        raise RuntimeError(
            "agent_foundry.mlflow_adapter.enable() requires "
            "run_context.telemetry_provider to be set. "
            "Pass telemetry=config to run_primitive_plan first."
        )

    ctx_id = id(run_context)
    with _ENABLED_CONTEXTS_LOCK:
        if ctx_id in _ENABLED_CONTEXT_IDS:
            return

        # Configure the MLflow client BEFORE attaching hooks so that when
        # on_open fires and calls mlflow.start_run, it lands in the right
        # tracking server + experiment. These are global mutations on the
        # mlflow library; subsequent enable() calls in the same process
        # overwrite them.
        if tracking_uri is not None:
            mlflow.set_tracking_uri(tracking_uri)
        if experiment_id is not None:
            mlflow.set_experiment(experiment_id=experiment_id)

        if config.run_definition is not None:
            attach_run_hooks(
                run_context=run_context,
                run_definition=config.run_definition,
                redaction=config.redaction,
                input_model=input_model,
            )

        _ENABLED_CONTEXT_IDS.add(ctx_id)
        weakref.finalize(run_context, _unregister, ctx_id)


__all__ = ["MLFLOW_TRANSLATIONS", "enable", "reset_for_testing"]
