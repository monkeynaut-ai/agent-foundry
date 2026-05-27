"""Tests that run_agent_in_container appends AgentTurnRecord to RunContext.observability_store."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.observability.models import AgentTurnRecord
from agent_foundry.observability.store import ObservabilityStore
from agent_foundry.orchestration import container_executor
from agent_foundry.orchestration.artifacts import bootstrap_run_artifacts
from agent_foundry.orchestration.container_executor import run_agent_in_container
from agent_foundry.orchestration.errors import AgentFailedError
from agent_foundry.orchestration.lifecycle_writer import NoOpLifecycleWriter
from agent_foundry.orchestration.registry import AgentContainerRegistry
from agent_foundry.orchestration.run_context import RunContext
from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy
from agent_foundry.responders.protocol import static_provider
from tests.agent_foundry.orchestration.fakes import (
    FakeClaudeCodeDriver,
    FakeContainerManager,
    FakeResponder,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class CapturingStore(ObservabilityStore):
    """In-memory store that captures every appended record."""

    def __init__(self) -> None:
        self.records: list[AgentTurnRecord] = []

    def append(self, record: AgentTurnRecord) -> None:
        self.records.append(record)

    def iter_records(self) -> Iterator[AgentTurnRecord]:
        return iter(self.records)

    def close(self) -> None:
        pass


class BrokenStore(ObservabilityStore):
    """Store whose append() always raises — used to test best-effort isolation."""

    def append(self, record: AgentTurnRecord) -> None:
        raise RuntimeError("store is broken")

    def iter_records(self) -> Iterator[AgentTurnRecord]:
        return iter([])

    def close(self) -> None:
        pass


class InputModel(BaseModel):
    task: str


class OutputModel(BaseModel):
    answer: str


def _make_primitive(*, model: str = "claude-sonnet-4-6") -> AgentAction:
    return AgentAction[InputModel, OutputModel](
        name="obs-agent",
        prompt_builder=lambda s: f"do: {s.task}",
        instructions_provider=lambda _: "be precise",
        executor=run_agent_in_container,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        model=model,
    )


def _success_env(answer: str = "42") -> dict[str, Any]:
    return {"outcome": {"kind": "success", "payload": {"answer": answer}}}


def _clarification_env(question: str = "which?") -> dict[str, Any]:
    return {
        "outcome": {
            "kind": "clarification_needed",
            "question": question,
            "options": [],
            "blocking": True,
        }
    }


def _failure_env(reason: str = "oops") -> dict[str, Any]:
    return {"outcome": {"kind": "failed", "reason": reason, "attempted_approaches": []}}


def _make_ctx(tmp_path: Path, store: ObservabilityStore, responder: Any = None) -> RunContext:
    fake_mgr = FakeContainerManager()
    registry = AgentContainerRegistry(
        manager=fake_mgr,
        base_image_tag="test:latest",
        workspace_volume="vol",
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    run_dir = bootstrap_run_artifacts(
        artifacts_dir=artifacts_dir,
        run_id="run-obs",
        workspace_volume="vol",
        base_image_tag="test:latest",
    )
    return RunContext(
        run_id="run-obs",
        artifacts_dir=run_dir,
        container_registry=registry,
        responder_provider=(static_provider(responder) if responder is not None else None),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
        observability_store=store,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_success_turn_appends_one_record(monkeypatch, tmp_path) -> None:
    """One turn that succeeds → exactly one record with correct field values."""
    store = CapturingStore()
    driver = FakeClaudeCodeDriver(
        turn_script=[_success_env("42")],
        session_ids=["sess-obs"],
    )
    monkeypatch.setattr(container_executor, "_run_claude_turn", driver)
    ctx = _make_ctx(tmp_path, store)
    primitive = _make_primitive()

    result = await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)

    assert result.answer == "42"  # type: ignore[attr-defined]
    assert len(store.records) == 1

    rec = store.records[0]
    assert rec.agent_name == "obs-agent"
    assert rec.turn_index == 0
    assert rec.outcome_kind == "success"
    assert rec.model == "claude-sonnet-4-6"
    assert rec.resume_retries == 0
    assert rec.duration_s >= 0.0
    assert rec.subagent_spawns == 0


@pytest.mark.asyncio
async def test_clarification_then_success_appends_two_records(monkeypatch, tmp_path) -> None:
    """Clarification → success produces two records in insertion order."""
    store = CapturingStore()
    driver = FakeClaudeCodeDriver(
        turn_script=[_clarification_env("which branch?"), _success_env("merged")],
        session_ids=["sess-obs"],
    )
    monkeypatch.setattr(container_executor, "_run_claude_turn", driver)
    responder = FakeResponder(answers=["main"])
    ctx = _make_ctx(tmp_path, store, responder=responder)
    primitive = _make_primitive()

    await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)

    assert len(store.records) == 2

    first = store.records[0]
    assert first.turn_index == 0
    assert first.outcome_kind == "clarification_needed"

    second = store.records[1]
    assert second.turn_index == 1
    assert second.outcome_kind == "success"


@pytest.mark.asyncio
async def test_failed_outcome_appends_record_before_raising(monkeypatch, tmp_path) -> None:
    """FailureOutcome still appends a record with outcome_kind='failed' before raising."""
    store = CapturingStore()
    driver = FakeClaudeCodeDriver(
        turn_script=[_failure_env("cannot proceed")],
        session_ids=["sess-obs"],
    )
    monkeypatch.setattr(container_executor, "_run_claude_turn", driver)
    ctx = _make_ctx(tmp_path, store)
    primitive = _make_primitive()

    with pytest.raises(AgentFailedError):
        await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)

    assert len(store.records) == 1
    assert store.records[0].outcome_kind == "failed"
    assert store.records[0].turn_index == 0


@pytest.mark.asyncio
async def test_broken_store_does_not_propagate_exception(monkeypatch, tmp_path) -> None:
    """If store.append() raises, the exception is swallowed — agent execution continues."""
    store = BrokenStore()
    driver = FakeClaudeCodeDriver(
        turn_script=[_success_env("ok")],
        session_ids=["sess-obs"],
    )
    monkeypatch.setattr(container_executor, "_run_claude_turn", driver)
    ctx = _make_ctx(tmp_path, store)
    primitive = _make_primitive()

    # Must not raise even though the store is broken.
    result = await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)
    assert result.answer == "ok"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_record_model_field_matches_primitive_model(monkeypatch, tmp_path) -> None:
    """AgentTurnRecord.model is sourced from AgentAction.model, not hard-coded."""
    store = CapturingStore()
    driver = FakeClaudeCodeDriver(
        turn_script=[_success_env()],
        session_ids=["sess-obs"],
    )
    monkeypatch.setattr(container_executor, "_run_claude_turn", driver)
    ctx = _make_ctx(tmp_path, store)
    primitive = _make_primitive(model="claude-opus-4-7")

    await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)

    assert store.records[0].model == "claude-opus-4-7"
