"""Tests for the eval task builders' RunOutcome adaptation.

``build_run_primitive_plan_task`` wraps ``run_primitive_plan`` (which
returns a ``RunOutcome``) into the Inspect ``Task`` contract, which is
exception-based: a completed run unwraps to its product output; a failed
or aborted run raises.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from agent_foundry.evals.agent_foundry_tasks import build_run_primitive_plan_task
from agent_foundry.orchestration import runner as runner_mod
from agent_foundry.orchestration.run_outcome import (
    FailureKind,
    RunAborted,
    RunCompleted,
    RunFailed,
)
from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy


class _In(BaseModel):
    task: str


class _Out(BaseModel):
    x: int


def _agent() -> AgentAction:
    return AgentAction[_In, _Out](
        name="planner",
        model="claude-sonnet-4-6",
        prompt_builder=lambda s: s.task,
        instructions_provider=lambda _s: "i",
        executor=lambda **_k: None,  # never called; run_primitive_plan is patched
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    )


def _build_task(monkeypatch, outcome, tmp_path: Path):
    async def _fake_run(*_a, **_k):
        return outcome

    monkeypatch.setattr(runner_mod, "run_primitive_plan", _fake_run)
    return build_run_primitive_plan_task(
        _agent(),
        artifacts_dir=tmp_path,
        workspace_volume="vol",
        base_image_tag="img",
    )


@pytest.mark.asyncio
async def test_task_unwraps_run_completed_output(monkeypatch, tmp_path: Path) -> None:
    task = _build_task(monkeypatch, RunCompleted(output=_Out(x=7)), tmp_path)
    result = await task(_In(task="go"))
    assert isinstance(result, _Out)
    assert result.x == 7


@pytest.mark.asyncio
async def test_task_raises_on_run_failed(monkeypatch, tmp_path: Path) -> None:
    outcome = RunFailed(error_kind=FailureKind.CRASH, error_type="RuntimeError", message="boom")
    task = _build_task(monkeypatch, outcome, tmp_path)
    with pytest.raises(Exception, match="boom"):
        await task(_In(task="go"))


@pytest.mark.asyncio
async def test_task_raises_on_run_aborted(monkeypatch, tmp_path: Path) -> None:
    task = _build_task(monkeypatch, RunAborted(reason="declined"), tmp_path)
    with pytest.raises(Exception, match="declined"):
        await task(_In(task="go"))
