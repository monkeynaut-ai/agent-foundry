"""Tests that RunContext carries an ObservabilityStore and defaults to NoOpObservabilityStore."""

import pytest
from pydantic import ValidationError

from agent_foundry.observability.store import JsonlObservabilityStore, NoOpObservabilityStore
from agent_foundry.orchestration.lifecycle_writer import NoOpLifecycleWriter
from agent_foundry.orchestration.registry import AgentContainerRegistry
from agent_foundry.orchestration.run_context import RunContext
from tests.agent_foundry.orchestration.fakes import FakeContainerManager


def _minimal_ctx(**overrides) -> RunContext:
    fake_mgr = FakeContainerManager()
    registry = AgentContainerRegistry(
        manager=fake_mgr,
        base_image_tag="test:latest",
        workspace_volume="vol",
    )
    return RunContext(
        run_id="test-run",
        container_registry=registry,
        lifecycle_writer=NoOpLifecycleWriter(),
        env={},
        **overrides,
    )


def test_default_observability_store_is_noop() -> None:
    ctx = _minimal_ctx()
    assert isinstance(ctx.observability_store, NoOpObservabilityStore)


def test_accepts_explicit_observability_store(tmp_path) -> None:
    store = JsonlObservabilityStore(tmp_path / "obs.jsonl")
    try:
        ctx = _minimal_ctx(observability_store=store)
        assert ctx.observability_store is store
    finally:
        store.close()


def test_frozen_ctx_rejects_store_reassignment() -> None:
    ctx = _minimal_ctx()
    with pytest.raises(ValidationError):
        ctx.observability_store = NoOpObservabilityStore()  # type: ignore[misc]
