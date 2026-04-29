"""Bind MLflow Run lifecycle to RunContext on_run_starting / on_run_ended hooks."""

from __future__ import annotations

import logging
import time
from typing import Any, cast

import mlflow
from pydantic import BaseModel

from agent_foundry.orchestration.run_context import (
    RunContext,
    RunEndedEvent,
    RunStartingEvent,
)
from agent_foundry.telemetry.config import (
    RedactionPolicy,
    RunDefinition,
    RunStats,
)

logger = logging.getLogger(__name__)


def _resolve_tags(tags: dict[str, str] | Any, input_model: BaseModel) -> dict[str, str]:
    if callable(tags):
        return cast(dict[str, str], tags(input_model))
    return dict(tags)


def attach_run_hooks(
    *,
    run_context: RunContext,
    run_definition: RunDefinition,
    redaction: RedactionPolicy | None,
    input_model: BaseModel,
) -> None:
    """Append on_run_starting / on_run_ended hooks to ``run_context`` that
    drive an MLflow Run.

    on_run_starting: evaluates ``run_definition.name`` / ``params`` /
    ``tags`` against ``input_model`` (with optional redaction applied to
    params), calls ``mlflow.start_run``, and logs the params. If any of
    these raises, the exception propagates to ``_safe_invoke_hooks``
    which logs and continues — ``state["mlflow_run_id"]`` stays None and
    the on_run_ended hook will become a no-op.

    on_run_ended: if on_run_starting did not successfully start an MLflow
    run, this is a no-op (a warning is logged). Otherwise builds a
    ``RunStats``, evaluates ``run_definition.metrics(output, stats)``
    against the run's final OUTPUT (or None on failure), logs metrics +
    artifacts, and ends the MLflow run with status FINISHED on success
    or FAILED if an exception was raised.
    """
    state: dict[str, Any] = {
        "start_time": None,
        "mlflow_run_id": None,
        "open_clean": False,
    }

    def on_run_starting(_event: RunStartingEvent) -> None:
        state["start_time"] = time.monotonic()
        name = run_definition.name(input_model)
        tags = _resolve_tags(run_definition.tags, input_model)

        # Redact the input before evaluating params so secrets never reach mlflow
        params_input = input_model
        if redaction is not None and redaction.redact_input is not None:
            params_input = redaction.redact_input(input_model)
        params = run_definition.params(params_input)

        run = mlflow.start_run(run_name=name, tags=tags)
        # Set mlflow_run_id ONLY after start_run succeeds — on_run_ended uses
        # this as a guard. open_clean stays False until log_params also
        # succeeds.
        state["mlflow_run_id"] = run.info.run_id
        mlflow.log_params(params)
        state["open_clean"] = True

    def on_run_ended(event: RunEndedEvent) -> None:
        if state["mlflow_run_id"] is None:
            # on_run_starting failed before start_run succeeded — no MLflow
            # run to close. Log a warning so the silent skip isn't truly
            # silent.
            logger.warning(
                "MLflow on_run_ended skipped — on_run_starting did not start "
                "a run (likely mlflow.start_run raised). Spans were emitted "
                "but no MLflow Run wraps them."
            )
            return

        # If on_run_starting partially succeeded (start_run ran but
        # log_params raised), treat the run as FAILED regardless of the
        # actual run outcome — the open was incomplete, the recorded params
        # are unreliable. Still close the run so it doesn't orphan in
        # RUNNING state.
        status = (
            "FAILED" if (event.exception is not None or not state["open_clean"]) else "FINISHED"
        )

        # The end_run call MUST always fire to close the MLflow run, even if
        # log_metrics or log_artifact raise. Use try/finally so an exception in
        # the middle doesn't orphan the run.
        try:
            if state["open_clean"]:
                duration_ms = (
                    (time.monotonic() - state["start_time"]) * 1000.0
                    if state["start_time"] is not None
                    else 0.0
                )
                stats = RunStats(duration_ms=duration_ms)

                try:
                    metrics = run_definition.metrics(event.output, stats)
                    if metrics:
                        mlflow.log_metrics(metrics)
                except Exception:
                    logger.exception(
                        "RunDefinition.metrics raised; skipping log_metrics. "
                        "MLflow run will still be closed."
                    )
                    status = "FAILED"

                for spec in run_definition.artifacts:
                    try:
                        mlflow.log_artifact(str(spec.path), spec.artifact_path)
                    except Exception:
                        logger.exception("log_artifact failed for %s; continuing", spec.path)
                        status = "FAILED"
        finally:
            mlflow.end_run(status=status)

    # RunContext is frozen — append to the mutable list rather than reassign.
    run_context.on_run_starting.append(on_run_starting)
    run_context.on_run_ended.append(on_run_ended)
