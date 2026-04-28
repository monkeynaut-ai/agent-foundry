"""Tests for telemetry threading through run_primitive_plan.

Per-run isolation: the runner builds a TracerProvider, anchors it on the
RunContext (via the new ``telemetry_provider`` field), and never calls
``trace.set_tracer_provider`` (which would be process-global). Tests verify
the provider is set on the context, used during the run, and shut down
afterward — without any process-global state.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from agent_foundry.orchestration.runner import run_primitive_plan
from agent_foundry.primitives.models import FunctionAction
from agent_foundry.primitives.plan import PrimitivePlan
from agent_foundry.telemetry import TelemetryConfig


class _State(BaseModel):
    value: str = "x"


def _plan() -> PrimitivePlan:
    def fn(s: _State) -> _State:
        return _State(value=s.value)

    return PrimitivePlan(root=FunctionAction[_State, _State](function=fn))


@pytest.mark.asyncio
async def test_run_primitive_plan_with_no_telemetry_leaves_run_context_provider_unset(
    tmp_path: Path,
) -> None:
    """telemetry=None → RunContext.telemetry_provider is None during execution."""
    observed: dict[str, object] = {}

    def capture(ctx) -> None:
        observed["provider"] = ctx.telemetry_provider
        observed["telemetry"] = ctx.telemetry

    await run_primitive_plan(
        _plan(),
        initial_state=_State(),
        artifacts_dir=tmp_path,
        workspace_volume="vol",
        base_image_tag="img",
        responder_provider=lambda _id: lambda *a, **k: None,
        run_id="r-no-tel",
        telemetry=None,
        on_open=[capture],
    )

    assert observed["provider"] is None
    assert observed["telemetry"] is None


@pytest.mark.asyncio
async def test_run_primitive_plan_with_telemetry_anchors_provider_on_run_context(
    tmp_path: Path,
) -> None:
    """When telemetry=config is passed, the runner builds a TracerProvider and
    stores it on RunContext.telemetry_provider. No global mutation of
    OTel's tracer-provider state.
    """
    from opentelemetry.sdk.trace import TracerProvider

    observed: dict[str, object] = {}

    config = TelemetryConfig(
        otlp_endpoint="http://localhost:5000/v1/traces",
        otlp_headers={"x-mlflow-experiment-id": "1"},
        service_name="archipelago-test",
    )

    def capture(ctx) -> None:
        observed["provider"] = ctx.telemetry_provider

    await run_primitive_plan(
        _plan(),
        initial_state=_State(),
        artifacts_dir=tmp_path,
        workspace_volume="vol",
        base_image_tag="img",
        responder_provider=lambda _id: lambda *a, **k: None,
        run_id="r-with-tel",
        telemetry=config,
        on_open=[capture],
    )

    assert isinstance(observed["provider"], TracerProvider)
    provider = observed["provider"]
    assert provider.resource.attributes.get("service.name") == "archipelago-test"


@pytest.mark.asyncio
async def test_run_primitive_plan_telemetry_provider_shut_down_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutdowns: list[bool] = []
    from agent_foundry.telemetry import setup as setup_mod

    original_build = setup_mod.build_tracer_provider

    def tracking_build(cfg):
        provider = original_build(cfg)
        original_shutdown = provider.shutdown

        def tracking_shutdown(*a, **k):
            shutdowns.append(True)
            return original_shutdown(*a, **k)

        provider.shutdown = tracking_shutdown  # type: ignore[method-assign]
        return provider

    monkeypatch.setattr(setup_mod, "build_tracer_provider", tracking_build)

    config = TelemetryConfig(
        otlp_endpoint="http://localhost:5000/v1/traces",
        otlp_headers={},
        service_name="archipelago-test",
    )

    await run_primitive_plan(
        _plan(),
        initial_state=_State(),
        artifacts_dir=tmp_path,
        workspace_volume="vol",
        base_image_tag="img",
        responder_provider=lambda _id: lambda *a, **k: None,
        run_id="r-shutdown",
        telemetry=config,
    )

    assert shutdowns == [True]


@pytest.mark.asyncio
async def test_run_primitive_plan_with_telemetry_does_not_mutate_global_tracer_provider(
    tmp_path: Path,
) -> None:
    """The runner must NOT call trace.set_tracer_provider — that would be a
    process-global mutation that breaks concurrent or sequential runs in the
    same process.
    """
    from opentelemetry import trace as otel_trace

    before = otel_trace.get_tracer_provider()

    config = TelemetryConfig(
        otlp_endpoint="http://localhost:5000/v1/traces",
        otlp_headers={},
        service_name="archipelago-test",
    )

    await run_primitive_plan(
        _plan(),
        initial_state=_State(),
        artifacts_dir=tmp_path,
        workspace_volume="vol",
        base_image_tag="img",
        responder_provider=lambda _id: lambda *a, **k: None,
        run_id="r-no-global",
        telemetry=config,
    )

    after = otel_trace.get_tracer_provider()
    assert after is before, (
        "Runner must not mutate the global tracer provider; install per-run on RunContext"
    )


@pytest.mark.asyncio
async def test_run_primitive_plan_cleans_up_run_dir_when_build_tracer_provider_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If build_tracer_provider raises, the bootstrapped run_dir must be
    cleaned up so failed runs don't leak directories on disk.
    """
    from agent_foundry.telemetry import setup as setup_mod

    def boom(_cfg):
        raise RuntimeError("bad telemetry config")

    monkeypatch.setattr(setup_mod, "build_tracer_provider", boom)

    config = TelemetryConfig(
        otlp_endpoint="http://localhost:5000/v1/traces",
        otlp_headers={},
        service_name="archipelago-test",
    )

    with pytest.raises(RuntimeError, match="bad telemetry config"):
        await run_primitive_plan(
            _plan(),
            initial_state=_State(),
            artifacts_dir=tmp_path,
            workspace_volume="vol",
            base_image_tag="img",
            responder_provider=lambda _id: lambda *a, **k: None,
            run_id="r-cleanup",
            telemetry=config,
        )

    leaked = list(tmp_path.glob("*r-cleanup*"))
    assert leaked == [], f"Expected no leaked run_dir; found: {leaked}"
