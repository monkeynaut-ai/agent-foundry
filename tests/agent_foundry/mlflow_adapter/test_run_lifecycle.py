"""Tests for the MLflow run lifecycle hooks."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.mlflow_adapter.run_lifecycle import attach_run_hooks
from agent_foundry.orchestration.run_context import (
    NoOpLifecycleWriter,
    RunContext,
    RunEndedEvent,
    RunStartingEvent,
)
from agent_foundry.telemetry.config import (
    ArtifactSpec,
    RedactionPolicy,
    RunDefinition,
)


class _In(BaseModel):
    ticket_id: str = "42"


class _Out(BaseModel):
    success: bool = True


class FakeMLflow:
    def __init__(self) -> None:
        self.start_run_calls: list[dict[str, Any]] = []
        self.log_params_calls: list[dict[str, Any]] = []
        self.log_metrics_calls: list[dict[str, Any]] = []
        self.log_artifact_calls: list[tuple[str, str | None]] = []
        self.end_run_calls: list[str] = []
        self._next_run_id = "mlflow-run-1"

    def start_run(self, run_name: str, tags: dict[str, str]) -> SimpleNamespace:
        self.start_run_calls.append({"run_name": run_name, "tags": tags})
        return SimpleNamespace(info=SimpleNamespace(run_id=self._next_run_id))

    def log_params(self, params: dict[str, Any]) -> None:
        self.log_params_calls.append(params)

    def log_metrics(self, metrics: dict[str, float]) -> None:
        self.log_metrics_calls.append(metrics)

    def log_artifact(self, local_path: str, artifact_path: str | None = None) -> None:
        self.log_artifact_calls.append((local_path, artifact_path))

    def end_run(self, status: str = "FINISHED") -> None:
        self.end_run_calls.append(status)


@pytest.fixture()
def fake_mlflow(monkeypatch: pytest.MonkeyPatch) -> FakeMLflow:
    fake = FakeMLflow()
    import agent_foundry.mlflow_adapter.run_lifecycle as mod

    monkeypatch.setattr(mod, "mlflow", fake, raising=False)
    return fake


def _ctx(tmp_path: Path) -> RunContext:
    return RunContext(
        run_id="r",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )


def _run_def() -> RunDefinition:
    return RunDefinition(
        name=lambda inp: f"ticket-{inp.ticket_id}",
        params=lambda inp: {"ticket_id": inp.ticket_id},
        tags={"product": "archipelago"},
        metrics=lambda out, stats: (
            {"duration_ms": stats.duration_ms, "success": float(out.success)}
            if out is not None
            else {"duration_ms": stats.duration_ms}
        ),
    )


def _starting(ctx: RunContext) -> RunStartingEvent:
    return RunStartingEvent(run_context=ctx)


def _ended(
    ctx: RunContext, exc: BaseException | None = None, output: BaseModel | None = None
) -> RunEndedEvent:
    return RunEndedEvent(run_context=ctx, exception=exc, output=output)


def test_on_run_starting_starts_run_and_logs_params(
    fake_mlflow: FakeMLflow, tmp_path: Path
) -> None:
    ctx = _ctx(tmp_path)
    attach_run_hooks(
        run_context=ctx,
        run_definition=_run_def(),
        redaction=None,
        input_model=_In(ticket_id="42"),
    )

    for hook in ctx.on_run_starting:
        hook(_starting(ctx))

    assert fake_mlflow.start_run_calls == [
        {"run_name": "ticket-42", "tags": {"product": "archipelago"}}
    ]
    assert fake_mlflow.log_params_calls == [{"ticket_id": "42"}]


def test_on_run_ended_logs_metrics_with_output_and_ends_run_finished(
    fake_mlflow: FakeMLflow, tmp_path: Path
) -> None:
    ctx = _ctx(tmp_path)
    attach_run_hooks(
        run_context=ctx,
        run_definition=_run_def(),
        redaction=None,
        input_model=_In(ticket_id="42"),
    )
    output = _Out(success=True)

    for hook in ctx.on_run_starting:
        hook(_starting(ctx))
    for hook in ctx.on_run_ended:
        hook(_ended(ctx, exc=None, output=output))

    assert len(fake_mlflow.log_metrics_calls) == 1
    logged = fake_mlflow.log_metrics_calls[0]
    assert "duration_ms" in logged
    assert logged["success"] == 1.0
    assert fake_mlflow.end_run_calls == ["FINISHED"]


def test_on_run_ended_with_exception_and_none_output_ends_run_failed(
    fake_mlflow: FakeMLflow, tmp_path: Path
) -> None:
    ctx = _ctx(tmp_path)
    attach_run_hooks(
        run_context=ctx,
        run_definition=_run_def(),
        redaction=None,
        input_model=_In(ticket_id="42"),
    )

    for hook in ctx.on_run_starting:
        hook(_starting(ctx))
    for hook in ctx.on_run_ended:
        hook(_ended(ctx, exc=RuntimeError("boom"), output=None))

    assert fake_mlflow.end_run_calls == ["FAILED"]
    assert len(fake_mlflow.log_metrics_calls) == 1
    assert "success" not in fake_mlflow.log_metrics_calls[0]


def test_on_run_ended_calls_end_run_even_when_metrics_callable_raises(
    fake_mlflow: FakeMLflow, tmp_path: Path
) -> None:
    """Undefended metrics callable raise (e.g. AttributeError on out.success
    when out is None) must NOT orphan the MLflow run in RUNNING state.
    """
    ctx = _ctx(tmp_path)
    bad_run_def = RunDefinition(
        name=lambda _: "n",
        params=lambda _: {},
        tags={},
        metrics=lambda out, stats: {"success": float(out.success)},
    )
    attach_run_hooks(
        run_context=ctx,
        run_definition=bad_run_def,
        redaction=None,
        input_model=_In(ticket_id="42"),
    )

    for hook in ctx.on_run_starting:
        hook(_starting(ctx))
    for hook in ctx.on_run_ended:
        hook(_ended(ctx, exc=RuntimeError("process failed"), output=None))

    assert fake_mlflow.end_run_calls == ["FAILED"]


def test_on_run_ended_treats_partial_open_as_failed(
    fake_mlflow: FakeMLflow,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If on_run_starting's mlflow.log_params raises after start_run
    succeeds, on_run_ended must still close the run with FAILED status (no
    orphan).
    """

    def boom_log_params(*a, **k):
        raise RuntimeError("log_params failed")

    fake_mlflow.log_params = boom_log_params  # type: ignore[method-assign]

    ctx = _ctx(tmp_path)
    attach_run_hooks(
        run_context=ctx,
        run_definition=_run_def(),
        redaction=None,
        input_model=_In(ticket_id="42"),
    )

    for hook in ctx.on_run_starting:
        with contextlib.suppress(RuntimeError):
            hook(_starting(ctx))

    for hook in ctx.on_run_ended:
        hook(_ended(ctx, exc=None, output=_Out(success=True)))

    assert fake_mlflow.end_run_calls == ["FAILED"]
    assert fake_mlflow.log_metrics_calls == []
    assert fake_mlflow.log_artifact_calls == []


def test_on_run_ended_skipped_when_on_run_starting_did_not_start_run(
    fake_mlflow: FakeMLflow,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If on_run_starting's mlflow.start_run raised, on_run_ended must not
    call MLflow APIs.
    """

    def boom_start_run(*a, **k):
        raise RuntimeError("mlflow start_run failed")

    fake_mlflow.start_run = boom_start_run  # type: ignore[method-assign]

    ctx = _ctx(tmp_path)
    attach_run_hooks(
        run_context=ctx,
        run_definition=_run_def(),
        redaction=None,
        input_model=_In(ticket_id="42"),
    )

    for hook in ctx.on_run_starting:
        with contextlib.suppress(RuntimeError):
            hook(_starting(ctx))

    with caplog.at_level(logging.WARNING):
        for hook in ctx.on_run_ended:
            hook(_ended(ctx, exc=None, output=_Out(success=True)))

    assert fake_mlflow.log_metrics_calls == []
    assert fake_mlflow.log_artifact_calls == []
    assert fake_mlflow.end_run_calls == []
    assert any("on_run_ended skipped" in record.message for record in caplog.records)


def test_on_run_starting_applies_redaction_to_params(
    fake_mlflow: FakeMLflow, tmp_path: Path
) -> None:
    ctx = _ctx(tmp_path)
    policy = RedactionPolicy(
        redact_input=lambda _m: _In(ticket_id="[REDACTED]"),
    )
    attach_run_hooks(
        run_context=ctx,
        run_definition=_run_def(),
        redaction=policy,
        input_model=_In(ticket_id="42"),
    )

    for hook in ctx.on_run_starting:
        hook(_starting(ctx))

    assert fake_mlflow.log_params_calls == [{"ticket_id": "[REDACTED]"}]


def test_on_run_ended_logs_artifacts(fake_mlflow: FakeMLflow, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    artifact_path = tmp_path / "result.json"
    artifact_path.write_text("{}")

    run_def = RunDefinition(
        name=lambda _: "n",
        params=lambda _: {},
        tags={},
        metrics=lambda _out, _s: {"x": 1.0},
        artifacts=[ArtifactSpec(path=artifact_path, artifact_path="results")],
    )
    attach_run_hooks(
        run_context=ctx,
        run_definition=run_def,
        redaction=None,
        input_model=_In(),
    )

    for hook in ctx.on_run_starting:
        hook(_starting(ctx))
    for hook in ctx.on_run_ended:
        hook(_ended(ctx, exc=None, output=_Out(success=True)))

    assert fake_mlflow.log_artifact_calls == [(str(artifact_path), "results")]
