"""Tests that run_primitive_plan creates and closes a JsonlObservabilityStore."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.observability.store import JsonlObservabilityStore
from agent_foundry.orchestration import registry as registry_mod
from agent_foundry.orchestration.runner import run_primitive_plan
from agent_foundry.primitives.models import FunctionAction
from agent_foundry.primitives.plan import PrimitivePlan
from agent_foundry.responders.protocol import static_provider
from tests.agent_foundry.orchestration.fakes import FakeContainerManager, FakeResponder

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_registry(monkeypatch) -> FakeContainerManager:
    """Inject FakeContainerManager into every AgentContainerRegistry built
    inside run_primitive_plan so the test never needs a real Docker daemon."""
    fake_mgr = FakeContainerManager()
    real_init = registry_mod.AgentContainerRegistry.__init__

    def _patched_init(
        self,
        *,
        workspace_volume: str,
        base_image_tag: str,
        docker_client_factory=None,
        manager=None,
        **extra: Any,
    ) -> None:
        real_init(
            self,
            workspace_volume=workspace_volume,
            base_image_tag=base_image_tag,
            docker_client_factory=docker_client_factory,
            manager=manager or fake_mgr,
            **extra,
        )

    monkeypatch.setattr(registry_mod.AgentContainerRegistry, "__init__", _patched_init)
    return fake_mgr


# ---------------------------------------------------------------------------
# Model fixtures for a minimal FunctionAction plan
# ---------------------------------------------------------------------------


class EchoInput(BaseModel):
    value: str


class EchoOutput(BaseModel):
    result: str


def _echo_plan() -> tuple[PrimitivePlan, EchoInput]:
    action = FunctionAction[EchoInput, EchoOutput](
        function=lambda s: EchoOutput(result=s.value),
    )
    return PrimitivePlan(root=action), EchoInput(value="hello")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_primitive_plan_creates_observability_jsonl(
    tmp_path: Path,
    patch_registry: FakeContainerManager,
) -> None:
    """After a successful run, observability.jsonl exists under run_dir."""
    plan, initial = _echo_plan()
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    await run_primitive_plan(
        plan,
        initial_state=initial,
        artifacts_dir=artifacts_dir,
        workspace_volume="test-vol",
        base_image_tag="test:latest",
        responder_provider=static_provider(FakeResponder(answers=[])),
        run_id="obs-run",
    )

    run_dir = artifacts_dir / "obs-run"
    obs_path = run_dir / "observability.jsonl"
    assert obs_path.exists(), f"expected observability.jsonl at {obs_path}"


@pytest.mark.asyncio
async def test_run_ctx_carries_jsonl_store_during_run(
    tmp_path: Path,
    patch_registry: FakeContainerManager,
) -> None:
    """The RunContext's observability_store is a JsonlObservabilityStore during execution."""
    plan, initial = _echo_plan()
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    captured_store: list[object] = []

    def capture(event: Any) -> None:
        captured_store.append(event.run_context.observability_store)

    await run_primitive_plan(
        plan,
        initial_state=initial,
        artifacts_dir=artifacts_dir,
        workspace_volume="test-vol",
        base_image_tag="test:latest",
        responder_provider=static_provider(FakeResponder(answers=[])),
        run_id="obs-store-check",
        on_run_starting=[capture],
    )

    assert len(captured_store) == 1
    assert isinstance(captured_store[0], JsonlObservabilityStore)


@pytest.mark.asyncio
async def test_observability_store_closed_after_run(
    tmp_path: Path,
    patch_registry: FakeContainerManager,
) -> None:
    """After run_primitive_plan completes, the store is closed and iter_records() works."""
    plan, initial = _echo_plan()
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    captured: dict[str, Any] = {}

    def capture(event: Any) -> None:
        captured["store"] = event.run_context.observability_store

    await run_primitive_plan(
        plan,
        initial_state=initial,
        artifacts_dir=artifacts_dir,
        workspace_volume="test-vol",
        base_image_tag="test:latest",
        responder_provider=static_provider(FakeResponder(answers=[])),
        run_id="obs-closed-check",
        on_run_starting=[capture],
    )

    store: JsonlObservabilityStore = captured["store"]
    # The store is closed — calling close() again must be a no-op (idempotent).
    store.close()
    # iter_records() opens the file fresh so it works post-close.
    records = list(store.iter_records())
    # FunctionAction runs produce no AgentTurnRecord entries.
    assert records == []
