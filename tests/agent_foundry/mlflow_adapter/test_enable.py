"""Integration test: enable() wires translation + run lifecycle into one call."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider
from pydantic import BaseModel

from agent_foundry.mlflow_adapter import enable
from agent_foundry.orchestration.run_context import NoOpLifecycleWriter, RunContext
from agent_foundry.telemetry.config import (
    RunDefinition,
    TelemetryConfig,
)


class _In(BaseModel):
    ticket_id: str = "42"


class FakeMLflow:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def start_run(self, run_name: str, tags: dict[str, str]) -> SimpleNamespace:
        self.calls.append(("start_run", {"run_name": run_name, "tags": tags}))
        return SimpleNamespace(info=SimpleNamespace(run_id="m-1"))

    def log_params(self, params: dict[str, Any]) -> None:
        self.calls.append(("log_params", params))

    def log_metrics(self, metrics: dict[str, float]) -> None:
        self.calls.append(("log_metrics", metrics))

    def log_artifact(self, *a, **k) -> None:
        self.calls.append(("log_artifact", {"args": a, "kwargs": k}))

    def end_run(self, status: str = "FINISHED") -> None:
        self.calls.append(("end_run", {"status": status}))


@pytest.fixture()
def fake_mlflow(monkeypatch: pytest.MonkeyPatch) -> FakeMLflow:
    fake = FakeMLflow()
    import agent_foundry.mlflow_adapter.run_lifecycle as mod

    monkeypatch.setattr(mod, "mlflow", fake, raising=False)
    return fake


@pytest.fixture(autouse=True)
def reset_adapter_state() -> Iterator[None]:
    """Clear the adapter's process-global idempotency sets between tests."""
    from agent_foundry.mlflow_adapter import reset_for_testing

    reset_for_testing()
    yield
    reset_for_testing()


def _ctx(
    tmp_path: Path,
    run_id: str = "r-default",
    provider: TracerProvider | None = None,
) -> RunContext:
    return RunContext(
        run_id=run_id,
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        telemetry_provider=provider,
    )


def _config() -> TelemetryConfig:
    return TelemetryConfig(
        otlp_endpoint="http://localhost:5000/v1/traces",
        otlp_headers={},
        service_name="archipelago-test",
        run_definition=RunDefinition(
            name=lambda inp: f"ticket-{inp.ticket_id}",
            params=lambda inp: {"ticket_id": inp.ticket_id},
            tags={},
            metrics=lambda _out, _s: {},
        ),
    )


def test_enable_does_not_register_a_span_processor(fake_mlflow: FakeMLflow, tmp_path: Path) -> None:
    """Translation happens via TelemetryConfig.attribute_translations at emit
    time — enable() must NOT add a SpanProcessor.
    """
    provider = TracerProvider()
    processors_before = list(
        provider._active_span_processor._span_processors  # type: ignore[attr-defined]
    )

    ctx = _ctx(tmp_path, run_id="r-no-processor", provider=provider)
    enable(config=_config(), run_context=ctx, input_model=_In(ticket_id="42"))

    processors_after = list(
        provider._active_span_processor._span_processors  # type: ignore[attr-defined]
    )
    assert len(processors_before) == len(processors_after)
    provider.shutdown()


def test_enable_attaches_run_lifecycle_hooks(fake_mlflow: FakeMLflow, tmp_path: Path) -> None:
    provider = TracerProvider()
    ctx = _ctx(tmp_path, run_id="r-hooks", provider=provider)
    enable(config=_config(), run_context=ctx, input_model=_In(ticket_id="7"))

    assert len(ctx.on_open) == 1
    assert len(ctx.on_close) == 1
    provider.shutdown()


def test_enable_is_idempotent_for_same_context(fake_mlflow: FakeMLflow, tmp_path: Path) -> None:
    provider = TracerProvider()
    ctx = _ctx(tmp_path, run_id="r-idem", provider=provider)

    enable(config=_config(), run_context=ctx, input_model=_In())
    enable(config=_config(), run_context=ctx, input_model=_In())

    assert len(ctx.on_open) == 1
    assert len(ctx.on_close) == 1
    provider.shutdown()


def test_enable_attaches_separate_hooks_for_distinct_contexts_with_same_run_id(
    fake_mlflow: FakeMLflow, tmp_path: Path
) -> None:
    """Idempotency keys on RunContext object identity, not run_id."""
    provider_a = TracerProvider()
    provider_b = TracerProvider()
    ctx_a = _ctx(tmp_path, run_id="shared", provider=provider_a)
    ctx_b = _ctx(tmp_path, run_id="shared", provider=provider_b)

    enable(config=_config(), run_context=ctx_a, input_model=_In())
    enable(config=_config(), run_context=ctx_b, input_model=_In())

    assert len(ctx_a.on_open) == 1
    assert len(ctx_b.on_open) == 1
    provider_a.shutdown()
    provider_b.shutdown()


def test_enable_raises_when_run_context_has_no_telemetry_provider(
    fake_mlflow: FakeMLflow, tmp_path: Path
) -> None:
    """Without a per-run TracerProvider on RunContext, enable() must fail loudly."""
    config = TelemetryConfig(
        otlp_endpoint="http://localhost:5000/v1/traces",
        otlp_headers={},
        service_name="archipelago-test",
    )
    ctx = _ctx(tmp_path, run_id="r-no-prov", provider=None)
    with pytest.raises(RuntimeError, match="telemetry_provider"):
        enable(config=config, run_context=ctx, input_model=_In())


def test_enable_sets_mlflow_tracking_uri_and_experiment_when_provided(
    fake_mlflow: FakeMLflow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When tracking_uri and experiment_id are passed, enable() configures
    the global mlflow client so subsequent mlflow.start_run / log_params calls
    target the right server + experiment.
    """
    import mlflow

    set_uri_calls: list[str] = []
    set_exp_calls: list[dict[str, str]] = []

    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: set_uri_calls.append(uri))
    monkeypatch.setattr(
        mlflow,
        "set_experiment",
        lambda *, experiment_id: set_exp_calls.append({"experiment_id": experiment_id}),
    )

    provider = TracerProvider()
    ctx = _ctx(tmp_path, run_id="r-mlflow-config", provider=provider)
    enable(
        config=_config(),
        run_context=ctx,
        input_model=_In(),
        tracking_uri="http://localhost:5000",
        experiment_id="7",
    )

    assert set_uri_calls == ["http://localhost:5000"]
    assert set_exp_calls == [{"experiment_id": "7"}]
    provider.shutdown()


def test_enable_omits_mlflow_client_config_when_not_provided(
    fake_mlflow: FakeMLflow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If tracking_uri / experiment_id aren't passed, enable() leaves the
    mlflow client's global state alone (caller relies on env vars or earlier
    configuration).
    """
    import mlflow

    set_uri_calls: list[str] = []
    set_exp_calls: list[dict[str, str]] = []

    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: set_uri_calls.append(uri))
    monkeypatch.setattr(
        mlflow,
        "set_experiment",
        lambda *, experiment_id: set_exp_calls.append({"experiment_id": experiment_id}),
    )

    provider = TracerProvider()
    ctx = _ctx(tmp_path, run_id="r-no-mlflow-config", provider=provider)
    enable(config=_config(), run_context=ctx, input_model=_In())

    assert set_uri_calls == []
    assert set_exp_calls == []
    provider.shutdown()
