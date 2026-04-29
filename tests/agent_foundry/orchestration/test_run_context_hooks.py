"""Tests for RunContext lifecycle hooks (on_run_starting / on_run_ended)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from agent_foundry.orchestration.run_context import (
    NoOpLifecycleWriter,
    RunContext,
    RunEndedEvent,
    RunStartingEvent,
)


def _ctx(tmp_path: Path, **overrides) -> RunContext:
    kwargs = dict(
        run_id="r",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    kwargs.update(overrides)
    return RunContext(**kwargs)


def test_run_context_on_run_starting_default_empty(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    assert ctx.on_run_starting == []


def test_run_context_on_run_ended_default_empty(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    assert ctx.on_run_ended == []


def test_run_context_accepts_on_run_starting_callables(tmp_path: Path) -> None:
    def hook(event: RunStartingEvent) -> None:
        pass

    rc = _ctx(tmp_path, on_run_starting=[hook])
    assert rc.on_run_starting == [hook]


def test_run_context_accepts_on_run_ended_callables(tmp_path: Path) -> None:
    def hook(event: RunEndedEvent) -> None:
        pass

    rc = _ctx(tmp_path, on_run_ended=[hook])
    assert rc.on_run_ended == [hook]


def test_run_context_on_run_starting_field_assignment_raises(tmp_path: Path) -> None:
    """frozen=True blocks field reassignment but list.append works.

    Documents the mutation pattern: ``ctx.on_run_starting.append(hook)`` is
    the supported way to add a hook after construction;
    ``ctx.on_run_starting = [hook]`` raises ValidationError.
    """
    ctx = _ctx(tmp_path)
    with pytest.raises(ValidationError):
        ctx.on_run_starting = [lambda _evt: None]


def test_run_context_on_run_starting_append_after_construction(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.on_run_starting.append(lambda _evt: None)
    assert len(ctx.on_run_starting) == 1


# -- Runner-side hook invocation --


class _State(BaseModel):
    value: str = "x"


@pytest.mark.asyncio
async def test_run_primitive_plan_invokes_on_run_starting_in_order(tmp_path: Path) -> None:
    from agent_foundry.orchestration.runner import run_primitive_plan
    from agent_foundry.primitives.models import FunctionAction
    from agent_foundry.primitives.plan import PrimitivePlan

    observed: list[str] = []
    hooks = [
        lambda evt: observed.append(f"open-1:{evt.run_context.run_id}"),
        lambda evt: observed.append(f"open-2:{evt.run_context.run_id}"),
    ]

    def fn(s: _State) -> _State:
        return _State(value=s.value)

    action = FunctionAction[_State, _State](function=fn)
    plan = PrimitivePlan(root=action)

    await run_primitive_plan(
        plan,
        initial_state=_State(),
        artifacts_dir=tmp_path,
        workspace_volume="vol",
        base_image_tag="img",
        responder_provider=lambda _id: lambda *a, **k: None,
        run_id="run-hooks",
        on_run_starting=hooks,
    )

    assert observed == ["open-1:run-hooks", "open-2:run-hooks"]


@pytest.mark.asyncio
async def test_run_primitive_plan_invokes_on_run_ended_with_exception_none_and_output_on_success(
    tmp_path: Path,
) -> None:
    from agent_foundry.orchestration.runner import run_primitive_plan
    from agent_foundry.primitives.models import FunctionAction
    from agent_foundry.primitives.plan import PrimitivePlan

    observed: list[RunEndedEvent] = []

    def fn(s: _State) -> _State:
        return _State(value=s.value)

    action = FunctionAction[_State, _State](function=fn)
    plan = PrimitivePlan(root=action)

    await run_primitive_plan(
        plan,
        initial_state=_State(),
        artifacts_dir=tmp_path,
        workspace_volume="vol",
        base_image_tag="img",
        responder_provider=lambda _id: lambda *a, **k: None,
        run_id="run-success",
        on_run_ended=[observed.append],
    )

    assert len(observed) == 1
    event = observed[0]
    assert event.exception is None
    assert isinstance(event.output, _State)


@pytest.mark.asyncio
async def test_run_primitive_plan_invokes_on_run_ended_with_exception_and_none_output_on_failure(
    tmp_path: Path,
) -> None:
    from agent_foundry.orchestration.runner import run_primitive_plan
    from agent_foundry.primitives.models import FunctionAction
    from agent_foundry.primitives.plan import PrimitivePlan

    observed: list[RunEndedEvent] = []

    def boom(_: _State) -> _State:
        raise RuntimeError("boom")

    action = FunctionAction[_State, _State](function=boom)
    plan = PrimitivePlan(root=action)

    with pytest.raises(RuntimeError, match="boom"):
        await run_primitive_plan(
            plan,
            initial_state=_State(),
            artifacts_dir=tmp_path,
            workspace_volume="vol",
            base_image_tag="img",
            responder_provider=lambda _id: lambda *a, **k: None,
            run_id="run-fail",
            on_run_ended=[observed.append],
        )

    assert len(observed) == 1
    event = observed[0]
    assert isinstance(event.exception, RuntimeError)
    assert "boom" in str(event.exception)
    assert event.output is None


@pytest.mark.asyncio
async def test_run_primitive_plan_writes_run_failed_lifecycle_event(
    tmp_path: Path,
) -> None:
    """The lifecycle JSONL must end with RUN_FAILED on the failure path
    so downstream consumers can distinguish 'died mid-run' from 'in progress'.
    """
    import json

    from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
    from agent_foundry.orchestration.runner import run_primitive_plan
    from agent_foundry.primitives.models import FunctionAction
    from agent_foundry.primitives.plan import PrimitivePlan

    def boom(_: _State) -> _State:
        raise RuntimeError("boom")

    action = FunctionAction[_State, _State](function=boom)
    plan = PrimitivePlan(root=action)

    with pytest.raises(RuntimeError, match="boom"):
        await run_primitive_plan(
            plan,
            initial_state=_State(),
            artifacts_dir=tmp_path,
            workspace_volume="vol",
            base_image_tag="img",
            responder_provider=lambda _id: lambda *a, **k: None,
            run_id="run-fail-lc",
        )

    lifecycle_path = next(tmp_path.rglob("lifecycle.jsonl"))
    events = [json.loads(line) for line in lifecycle_path.read_text().splitlines()]
    types = [e["type"] for e in events]
    assert LifecycleEvent.RUN_STARTED.value in types
    assert LifecycleEvent.RUN_FAILED.value in types
    assert LifecycleEvent.RUN_ENDED.value not in types


@pytest.mark.asyncio
async def test_run_primitive_plan_writes_run_ended_lifecycle_event_on_success(
    tmp_path: Path,
) -> None:
    import json

    from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
    from agent_foundry.orchestration.runner import run_primitive_plan
    from agent_foundry.primitives.models import FunctionAction
    from agent_foundry.primitives.plan import PrimitivePlan

    def fn(s: _State) -> _State:
        return _State(value=s.value)

    action = FunctionAction[_State, _State](function=fn)
    plan = PrimitivePlan(root=action)

    await run_primitive_plan(
        plan,
        initial_state=_State(),
        artifacts_dir=tmp_path,
        workspace_volume="vol",
        base_image_tag="img",
        responder_provider=lambda _id: lambda *a, **k: None,
        run_id="run-ok-lc",
    )

    lifecycle_path = next(tmp_path.rglob("lifecycle.jsonl"))
    events = [json.loads(line) for line in lifecycle_path.read_text().splitlines()]
    types = [e["type"] for e in events]
    assert LifecycleEvent.RUN_STARTED.value in types
    assert LifecycleEvent.RUN_ENDED.value in types
    assert LifecycleEvent.RUN_FAILED.value not in types


@pytest.mark.asyncio
async def test_run_primitive_plan_isolates_hook_exceptions(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from agent_foundry.orchestration.runner import run_primitive_plan
    from agent_foundry.primitives.models import FunctionAction
    from agent_foundry.primitives.plan import PrimitivePlan

    observed: list[str] = []

    def fn(s: _State) -> _State:
        return _State(value=s.value)

    action = FunctionAction[_State, _State](function=fn)
    plan = PrimitivePlan(root=action)

    def bad(_evt: RunStartingEvent) -> None:
        raise ValueError("hook-1 failed")

    def good(_evt: RunStartingEvent) -> None:
        observed.append("hook-2 ran")

    with caplog.at_level(logging.ERROR):
        await run_primitive_plan(
            plan,
            initial_state=_State(),
            artifacts_dir=tmp_path,
            workspace_volume="vol",
            base_image_tag="img",
            responder_provider=lambda _id: lambda *a, **k: None,
            run_id="run-iso",
            on_run_starting=[bad, good],
        )

    assert observed == ["hook-2 ran"]
    # logger.exception writes the exception detail into the formatted output
    # (record.exc_text), not record.message — caplog.text combines both.
    assert "hook-1 failed" in caplog.text
