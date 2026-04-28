"""Tests for RunContext lifecycle hooks (on_open / on_close)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from agent_foundry.orchestration.run_context import (
    NoOpLifecycleWriter,
    RunContext,
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


def test_run_context_on_open_default_empty(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    assert ctx.on_open == []


def test_run_context_on_close_default_empty(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    assert ctx.on_close == []


def test_run_context_accepts_on_open_callables(tmp_path: Path) -> None:
    def hook(ctx: RunContext) -> None:
        pass

    rc = _ctx(tmp_path, on_open=[hook])
    assert rc.on_open == [hook]


def test_run_context_accepts_on_close_callables(tmp_path: Path) -> None:
    def hook(ctx: RunContext, exc: BaseException | None, output: BaseModel | None) -> None:
        pass

    rc = _ctx(tmp_path, on_close=[hook])
    assert rc.on_close == [hook]


def test_run_context_on_open_field_assignment_raises(tmp_path: Path) -> None:
    """frozen=True blocks field reassignment but list.append works.

    Documents the mutation pattern: `ctx.on_open.append(hook)` is the supported way
    to add a hook after construction; `ctx.on_open = [hook]` raises ValidationError.
    """
    ctx = _ctx(tmp_path)
    with pytest.raises(ValidationError):
        ctx.on_open = [lambda c: None]


def test_run_context_on_open_append_after_construction(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.on_open.append(lambda c: None)
    assert len(ctx.on_open) == 1


# -- Runner-side hook invocation --


class _Empty(BaseModel):
    value: str = "x"


@pytest.mark.asyncio
async def test_run_primitive_plan_invokes_on_open_in_order(tmp_path: Path) -> None:
    from agent_foundry.orchestration.runner import run_primitive_plan
    from agent_foundry.primitives.models import FunctionAction
    from agent_foundry.primitives.plan import PrimitivePlan

    observed: list[str] = []
    hooks = [
        lambda ctx: observed.append(f"open-1:{ctx.run_id}"),
        lambda ctx: observed.append(f"open-2:{ctx.run_id}"),
    ]

    def fn(_: _Empty) -> _Empty:
        return _Empty()

    action = FunctionAction[_Empty, _Empty](function=fn)
    plan = PrimitivePlan(root=action)

    await run_primitive_plan(
        plan,
        initial_state=_Empty(),
        artifacts_dir=tmp_path,
        workspace_volume="vol",
        base_image_tag="img",
        responder_provider=lambda _id: lambda *a, **k: None,
        run_id="run-hooks",
        on_open=hooks,
    )

    assert observed == ["open-1:run-hooks", "open-2:run-hooks"]


@pytest.mark.asyncio
async def test_run_primitive_plan_invokes_on_close_with_none_exc_and_output_on_success(
    tmp_path: Path,
) -> None:
    from agent_foundry.orchestration.runner import run_primitive_plan
    from agent_foundry.primitives.models import FunctionAction
    from agent_foundry.primitives.plan import PrimitivePlan

    observed: list[tuple[BaseException | None, BaseModel | None]] = []

    def fn(_: _Empty) -> _Empty:
        return _Empty()

    action = FunctionAction[_Empty, _Empty](function=fn)
    plan = PrimitivePlan(root=action)

    await run_primitive_plan(
        plan,
        initial_state=_Empty(),
        artifacts_dir=tmp_path,
        workspace_volume="vol",
        base_image_tag="img",
        responder_provider=lambda _id: lambda *a, **k: None,
        run_id="run-success",
        on_close=[lambda _ctx, exc, output: observed.append((exc, output))],
    )

    assert len(observed) == 1
    exc, output = observed[0]
    assert exc is None
    assert isinstance(output, _Empty)


@pytest.mark.asyncio
async def test_run_primitive_plan_invokes_on_close_with_exception_and_none_output_on_failure(
    tmp_path: Path,
) -> None:
    from agent_foundry.orchestration.runner import run_primitive_plan
    from agent_foundry.primitives.models import FunctionAction
    from agent_foundry.primitives.plan import PrimitivePlan

    observed: list[tuple[BaseException | None, BaseModel | None]] = []

    def boom(_: _Empty) -> _Empty:
        raise RuntimeError("boom")

    action = FunctionAction[_Empty, _Empty](function=boom)
    plan = PrimitivePlan(root=action)

    with pytest.raises(RuntimeError, match="boom"):
        await run_primitive_plan(
            plan,
            initial_state=_Empty(),
            artifacts_dir=tmp_path,
            workspace_volume="vol",
            base_image_tag="img",
            responder_provider=lambda _id: lambda *a, **k: None,
            run_id="run-fail",
            on_close=[lambda _ctx, exc, output: observed.append((exc, output))],
        )

    assert len(observed) == 1
    exc, output = observed[0]
    assert isinstance(exc, RuntimeError)
    assert "boom" in str(exc)
    assert output is None


@pytest.mark.asyncio
async def test_run_primitive_plan_writes_run_failed_lifecycle_event(
    tmp_path: Path,
) -> None:
    """The lifecycle JSONL must end with RUN_FAILED on the failure path
    so downstream consumers can distinguish 'died mid-run' from 'in progress'."""
    import json

    from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
    from agent_foundry.orchestration.runner import run_primitive_plan
    from agent_foundry.primitives.models import FunctionAction
    from agent_foundry.primitives.plan import PrimitivePlan

    def boom(_: _Empty) -> _Empty:
        raise RuntimeError("boom")

    action = FunctionAction[_Empty, _Empty](function=boom)
    plan = PrimitivePlan(root=action)

    with pytest.raises(RuntimeError, match="boom"):
        await run_primitive_plan(
            plan,
            initial_state=_Empty(),
            artifacts_dir=tmp_path,
            workspace_volume="vol",
            base_image_tag="img",
            responder_provider=lambda _id: lambda *a, **k: None,
            run_id="run-fail-lc",
        )

    lifecycle_path = next(tmp_path.rglob("lifecycle.jsonl"))
    events = [json.loads(line) for line in lifecycle_path.read_text().splitlines()]
    types = [e["type"] for e in events]
    # Use membership rather than position so a future on_close hook that
    # emits a domain event doesn't break the test. The contract is "exactly
    # one terminal event, and it's RUN_FAILED" — not "RUN_FAILED is last".
    # Use ``.value`` for parity with the existing test_run_primitive_plan tests.
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

    def fn(_: _Empty) -> _Empty:
        return _Empty()

    action = FunctionAction[_Empty, _Empty](function=fn)
    plan = PrimitivePlan(root=action)

    await run_primitive_plan(
        plan,
        initial_state=_Empty(),
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

    def fn(_: _Empty) -> _Empty:
        return _Empty()

    action = FunctionAction[_Empty, _Empty](function=fn)
    plan = PrimitivePlan(root=action)

    def bad(_ctx) -> None:
        raise ValueError("hook-1 failed")

    def good(_ctx) -> None:
        observed.append("hook-2 ran")

    with caplog.at_level(logging.ERROR):
        await run_primitive_plan(
            plan,
            initial_state=_Empty(),
            artifacts_dir=tmp_path,
            workspace_volume="vol",
            base_image_tag="img",
            responder_provider=lambda _id: lambda *a, **k: None,
            run_id="run-iso",
            on_open=[bad, good],
        )

    assert observed == ["hook-2 ran"]
    # logger.exception writes the exception detail into the formatted output
    # (record.exc_text), not record.message — caplog.text combines both.
    assert "hook-1 failed" in caplog.text
