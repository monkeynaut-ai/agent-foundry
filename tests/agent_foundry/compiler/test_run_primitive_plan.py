"""End-to-end tests for the async ``run_primitive_plan`` entry point.

The async entry point builds a ``RunContext`` from explicit
parameters, installs signal handlers (best-effort), sets the
``current_run_context`` ContextVar, compiles the plan, runs it via
``graph.ainvoke``, and writes ``summary.txt`` in a ``finally`` block.

These tests drive the new contract with a scripted
``FakeClaudeCodeDriver`` wired via the module-level
``set_driver_factory`` seam on :mod:`container_executor`. They are
expected to fail RED until the async entry point is implemented.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.orchestration import container_executor
from agent_foundry.orchestration.container_executor import run_agent_in_container
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.run_outcome import (
    FailureKind,
    RunAborted,
    RunCompleted,
    RunFailed,
)
from agent_foundry.primitives.models import (
    AgentAction,
    ContainerReusePolicy,
    FunctionAction,
    Retry,
    Sequence,
)
from agent_foundry.primitives.plan import PrimitivePlan
from agent_foundry.primitives.retry_types import DispositionKind, ResolverDisposition
from agent_foundry.responders.protocol import static_provider

from ..orchestration.fakes import (
    FakeClaudeCodeDriver,
    FakeContainerManager,
    FakeResponder,
)

# --- Models -----------------------------------------------------------------


class PlanInput(BaseModel):
    task: str


class AgentOut(BaseModel):
    x: int


class PlanOutput(BaseModel):
    x: int


# --- Envelope helpers -------------------------------------------------------


def _success_env(x: int = 1) -> dict[str, Any]:
    return {"outcome": {"kind": "success", "payload": {"x": x}}}


def _failure_env(reason: str = "nope") -> dict[str, Any]:
    return {"outcome": {"kind": "failed", "reason": reason, "attempted_approaches": []}}


# --- Driver / registry wiring ----------------------------------------------


@pytest.fixture
def fake_manager() -> FakeContainerManager:
    return FakeContainerManager()


@pytest.fixture
def install_driver(monkeypatch):
    """Install a scripted ``run_turn`` for the duration of a test.

    Returns a callable that takes a ``FakeClaudeCodeDriver``
    (awaitable-callable matching ``_run_claude_turn``) and monkeypatches
    it onto the module. Teardown restores the original symbol.
    """

    def _install(driver: FakeClaudeCodeDriver) -> None:
        monkeypatch.setattr(container_executor, "_run_claude_turn", driver)

    yield _install


@pytest.fixture
def patch_registry_manager(monkeypatch, fake_manager: FakeContainerManager):
    """Force every ``AgentContainerRegistry`` built inside
    ``run_primitive_plan`` to use our ``FakeContainerManager``
    regardless of how the entry point constructs the registry.
    """
    from agent_foundry.orchestration import registry as registry_mod

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
            manager=manager or fake_manager,
            **extra,
        )

    monkeypatch.setattr(registry_mod.AgentContainerRegistry, "__init__", _patched_init)
    return fake_manager


# --- Primitive builders -----------------------------------------------------


def _agent_primitive() -> AgentAction:
    return AgentAction[PlanInput, AgentOut](
        name="planner",
        model="claude-sonnet-4-6",
        prompt_builder=lambda s: f"do: {s.task}",
        instructions_provider=lambda _s: "instructions",
        executor=run_agent_in_container,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    )


def _double_fn(state: AgentOut) -> PlanOutput:
    return PlanOutput(x=state.x * 2)


def _plan_sequence() -> PrimitivePlan:
    class _SeqMid(BaseModel):
        task: str
        x: int

    agent = _agent_primitive()
    fn = FunctionAction[AgentOut, PlanOutput](function=_double_fn)
    seq = Sequence[PlanInput, PlanOutput](steps=[agent, fn])
    return PrimitivePlan(root=seq)


# --- Resolver/crash plan builders (no container needed) ---------------------


class _RetryState(BaseModel):
    """State for the resolver Retry plans: the automated reviewer never passes
    until() so the resolver seat is always consulted."""

    verdict: str = "fail"
    disposition: ResolverDisposition | None = None


def _never_passing_body() -> FunctionAction:
    def _fn(s: _RetryState) -> _RetryState:
        return _RetryState(verdict="fail", disposition=s.disposition)

    return FunctionAction[_RetryState, _RetryState](function=_fn)


def _plan_with_abort_resolver(reason: str) -> PrimitivePlan:
    """A Retry whose resolver ABORTs on the first consult."""

    def _abort(s: _RetryState) -> _RetryState:
        return _RetryState(
            verdict=s.verdict,
            disposition=ResolverDisposition(kind=DispositionKind.ABORT, reason=reason),
        )

    retry = Retry[_RetryState, _RetryState](
        max_attempts=1,
        until=lambda s: s.verdict == "pass",
        body=_never_passing_body(),
        on_max_attempts_resolver=FunctionAction[_RetryState, _RetryState](function=_abort),
    )
    return PrimitivePlan(root=retry)


def _plan_that_never_converges() -> PrimitivePlan:
    """A Retry whose resolver always RETRYs and whose body never passes until(),
    with a small backstop ceiling so ResolverDidNotConvergeError trips."""

    def _always_retry(s: _RetryState) -> _RetryState:
        return _RetryState(
            verdict=s.verdict,
            disposition=ResolverDisposition(kind=DispositionKind.RETRY, reason="more"),
        )

    retry = Retry[_RetryState, _RetryState](
        max_attempts=1,
        until=lambda s: s.verdict == "pass",
        body=_never_passing_body(),
        on_max_attempts_resolver=FunctionAction[_RetryState, _RetryState](function=_always_retry),
        resolver_max_reentries=3,
    )
    return PrimitivePlan(root=retry)


class _CrashOut(BaseModel):
    ok: bool = True


def _plan_with_raising_action(message: str) -> PrimitivePlan:
    def _boom(_: PlanInput) -> _CrashOut:
        raise RuntimeError(message)

    action = FunctionAction[PlanInput, _CrashOut](function=_boom)
    return PrimitivePlan(root=action)


def _lifecycle_types(run_dir: Path) -> list[str]:
    jsonl = run_dir / "lifecycle.jsonl"
    return [json.loads(line)["type"] for line in jsonl.read_text().splitlines() if line.strip()]


async def _run_resolver_plan(plan: PrimitivePlan, *, run_id: str, artifacts_dir: Path, **kwargs):
    """Run a resolver/crash plan (no container) via run_primitive_plan."""
    from agent_foundry.orchestration.runner import run_primitive_plan

    return await run_primitive_plan(
        plan,
        initial_state=_RetryState() if not kwargs.pop("crash", False) else PlanInput(task="x"),
        artifacts_dir=artifacts_dir,
        workspace_volume="vol",
        base_image_tag="img",
        responder_provider=static_provider(FakeResponder(answers=[])),
        run_id=run_id,
        **kwargs,
    )


# --- Tests -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_runs_end_to_end(
    tmp_path: Path,
    install_driver,
    patch_registry_manager,
):
    """One AgentAction + one FunctionAction run; final state has x==2;
    lifecycle.jsonl contains RUN_STARTED and RUN_ENDED; summary.txt written.
    """
    from agent_foundry.orchestration.runner import run_primitive_plan

    driver = FakeClaudeCodeDriver(turn_script=[_success_env(x=1)])
    install_driver(driver)

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    result = await run_primitive_plan(
        _plan_sequence(),
        initial_state=PlanInput(task="hello"),
        artifacts_dir=artifacts_dir,
        workspace_volume="vol-g2",
        base_image_tag="agent-foundry-base:test",
        responder_provider=static_provider(FakeResponder(answers=[])),
        run_id="run-happy",
    )

    assert isinstance(result, RunCompleted)
    assert isinstance(result.output, PlanOutput)
    assert result.output.x == 2

    run_dir = artifacts_dir / "run-happy"
    assert run_dir.is_dir()
    assert (run_dir / "summary.txt").is_file()

    jsonl = run_dir / "lifecycle.jsonl"
    assert jsonl.is_file()
    types = [json.loads(line)["type"] for line in jsonl.read_text().splitlines() if line.strip()]
    assert LifecycleEvent.RUN_STARTED.value in types
    assert LifecycleEvent.RUN_ENDED.value in types


@pytest.mark.asyncio
async def test_explicit_run_id_honored(
    tmp_path: Path,
    install_driver,
    patch_registry_manager,
):
    from agent_foundry.orchestration.runner import run_primitive_plan

    driver = FakeClaudeCodeDriver(turn_script=[_success_env(x=1)])
    install_driver(driver)

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    await run_primitive_plan(
        _plan_sequence(),
        initial_state=PlanInput(task="hi"),
        artifacts_dir=artifacts_dir,
        workspace_volume="vol",
        base_image_tag="base:test",
        responder_provider=static_provider(FakeResponder(answers=[])),
        run_id="my-explicit-id",
    )

    assert (artifacts_dir / "my-explicit-id").is_dir()


@pytest.mark.asyncio
async def test_implicit_run_id_unique_per_invocation(
    tmp_path: Path,
    install_driver,
    patch_registry_manager,
):
    from agent_foundry.orchestration.runner import run_primitive_plan

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    # Two back-to-back invocations with no run_id → two distinct run dirs.
    install_driver(FakeClaudeCodeDriver(turn_script=[_success_env(x=1)]))
    await run_primitive_plan(
        _plan_sequence(),
        initial_state=PlanInput(task="a"),
        artifacts_dir=artifacts_dir,
        workspace_volume="vol",
        base_image_tag="base:test",
        responder_provider=static_provider(FakeResponder(answers=[])),
    )

    install_driver(FakeClaudeCodeDriver(turn_script=[_success_env(x=1)]))
    await run_primitive_plan(
        _plan_sequence(),
        initial_state=PlanInput(task="b"),
        artifacts_dir=artifacts_dir,
        workspace_volume="vol",
        base_image_tag="base:test",
        responder_provider=static_provider(FakeResponder(answers=[])),
    )

    subdirs = [p for p in artifacts_dir.iterdir() if p.is_dir()]
    assert len(subdirs) == 2, f"expected two distinct run dirs, got {subdirs}"


@pytest.mark.asyncio
async def test_cancel_mid_run_propagates_and_cleans_up(
    tmp_path: Path,
    install_driver,
    patch_registry_manager,
    monkeypatch,
):
    """Setting ``cancel_event`` before the agent's first turn causes
    ``AgentFailedError('cancelled')`` to propagate; ``shutdown_all`` and
    ``render_summary`` still run in the finally block.
    """
    from agent_foundry.orchestration import registry as registry_mod
    from agent_foundry.orchestration.run_context import current_run_context
    from agent_foundry.orchestration.runner import run_primitive_plan

    driver = FakeClaudeCodeDriver(turn_script=[_success_env(x=1)])
    install_driver(driver)

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    # Set the run_ctx.cancel_event at registry get_or_create time — this
    # is the first executor touchpoint after run_primitive_plan has set
    # the current_run_context ContextVar. The executor's pre-turn check
    # then sees a set event and raises AgentFailedError("cancelled").
    real_get = registry_mod.AgentContainerRegistry.get_or_create

    async def _cancelling_get(
        self,
        primitive,
        *,
        lifecycle_writer,
        agent_name,
        instructions=None,
        extra_env=None,
        extra_volumes=None,
    ):
        live = await real_get(
            self,
            primitive,
            lifecycle_writer=lifecycle_writer,
            agent_name=agent_name,
            instructions=instructions,
        )
        ctx = current_run_context.get()
        if ctx is not None:
            ctx.cancel_event.set()
        return live

    monkeypatch.setattr(registry_mod.AgentContainerRegistry, "get_or_create", _cancelling_get)

    result = await run_primitive_plan(
        _plan_sequence(),
        initial_state=PlanInput(task="hi"),
        artifacts_dir=artifacts_dir,
        workspace_volume="vol",
        base_image_tag="base:test",
        responder_provider=static_provider(FakeResponder(answers=[])),
        run_id="run-cancel",
    )

    assert isinstance(result, RunFailed)
    assert result.error_kind is FailureKind.CRASH
    assert result.error_type == "AgentFailedError"
    assert "cancelled" in result.message

    run_dir = artifacts_dir / "run-cancel"
    # Summary still written even after cancel.
    assert (run_dir / "summary.txt").is_file()
    # Registry shutdown happened — the failed container is retained for
    # postmortem (pause_on_failure defaults to True), so it does NOT
    # appear in destroyed_ids. The retention message is logged at WARNING.
    assert patch_registry_manager.destroyed_ids == [], (
        "default pause_on_failure=True should retain the failed container"
    )


@pytest.mark.asyncio
async def test_exception_mid_run_propagates_and_cleans_up(
    tmp_path: Path,
    install_driver,
    patch_registry_manager,
):
    """Executor raises (FailureOutcome) → AgentFailedError becomes
    RunFailed(CRASH) (no re-raise); teardown still runs: registry handled
    + summary.txt written.
    """
    from agent_foundry.orchestration.runner import run_primitive_plan

    driver = FakeClaudeCodeDriver(turn_script=[_failure_env("boom")])
    install_driver(driver)

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    result = await run_primitive_plan(
        _plan_sequence(),
        initial_state=PlanInput(task="hi"),
        artifacts_dir=artifacts_dir,
        workspace_volume="vol",
        base_image_tag="base:test",
        responder_provider=static_provider(FakeResponder(answers=[])),
        run_id="run-fail",
    )

    assert isinstance(result, RunFailed)
    assert result.error_kind is FailureKind.CRASH

    run_dir = artifacts_dir / "run-fail"
    assert (run_dir / "summary.txt").is_file()
    # Failed container retained by default (pause_on_failure=True).
    assert patch_registry_manager.destroyed_ids == [], (
        "default pause_on_failure=True should retain the failed container"
    )


# --- Terminal-outcome classification (RunOutcome envelope) ------------------


@pytest.mark.asyncio
async def test_completed_returns_run_completed(
    tmp_path: Path,
    install_driver,
    patch_registry_manager,
) -> None:
    install_driver(FakeClaudeCodeDriver(turn_script=[_success_env(x=1)]))
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    from agent_foundry.orchestration.runner import run_primitive_plan

    result = await run_primitive_plan(
        _plan_sequence(),
        initial_state=PlanInput(task="hello"),
        artifacts_dir=artifacts_dir,
        workspace_volume="vol",
        base_image_tag="img",
        responder_provider=static_provider(FakeResponder(answers=[])),
        run_id="run-completed",
    )

    assert isinstance(result, RunCompleted)
    assert isinstance(result.output, PlanOutput)
    assert result.output.x == 2
    types = _lifecycle_types(artifacts_dir / "run-completed")
    assert LifecycleEvent.RUN_ENDED.value in types
    assert LifecycleEvent.RUN_ABORTED.value not in types
    assert LifecycleEvent.RUN_FAILED.value not in types


@pytest.mark.asyncio
async def test_resolver_abort_returns_run_aborted(tmp_path: Path) -> None:
    """ABORT -> RunAborted (does NOT raise); terminal event RUN_ABORTED."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    result = await _run_resolver_plan(
        _plan_with_abort_resolver("cannot-converge"),
        run_id="run-aborted",
        artifacts_dir=artifacts_dir,
    )

    assert isinstance(result, RunAborted)
    assert result.reason == "cannot-converge"
    types = _lifecycle_types(artifacts_dir / "run-aborted")
    assert LifecycleEvent.RUN_ABORTED.value in types
    assert LifecycleEvent.RUN_FAILED.value not in types
    assert LifecycleEvent.RUN_ENDED.value not in types


@pytest.mark.asyncio
async def test_abort_on_run_ended_hook_sees_outcome(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    captured: list = []

    await _run_resolver_plan(
        _plan_with_abort_resolver("cannot-converge"),
        run_id="run-aborted-hook",
        artifacts_dir=artifacts_dir,
        on_run_ended=[captured.append],
    )

    (ev,) = captured
    assert isinstance(ev.outcome, RunAborted)
    assert ev.outcome.reason == "cannot-converge"
    assert ev.exception is None
    assert ev.output is None


@pytest.mark.asyncio
async def test_backstop_returns_run_failed_backstop(tmp_path: Path) -> None:
    """ResolverDidNotConvergeError -> RunFailed(BACKSTOP), does NOT raise;
    terminal event RUN_FAILED."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    result = await _run_resolver_plan(
        _plan_that_never_converges(),
        run_id="run-backstop",
        artifacts_dir=artifacts_dir,
    )

    assert isinstance(result, RunFailed)
    assert result.error_kind is FailureKind.BACKSTOP
    assert result.error_type == "ResolverDidNotConvergeError"
    types = _lifecycle_types(artifacts_dir / "run-backstop")
    assert LifecycleEvent.RUN_FAILED.value in types
    assert LifecycleEvent.RUN_ABORTED.value not in types


@pytest.mark.asyncio
async def test_backstop_run_failed_record_carries_error_kind(tmp_path: Path) -> None:
    """The RUN_FAILED lifecycle record carries error_kind so render_summary
    reads one field (D7a)."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    await _run_resolver_plan(
        _plan_that_never_converges(),
        run_id="run-backstop-rec",
        artifacts_dir=artifacts_dir,
    )

    jsonl = artifacts_dir / "run-backstop-rec" / "lifecycle.jsonl"
    records = [json.loads(line) for line in jsonl.read_text().splitlines() if line.strip()]
    failed = [r for r in records if r["type"] == LifecycleEvent.RUN_FAILED.value]
    assert failed
    assert failed[-1]["error_kind"] == FailureKind.BACKSTOP.value


@pytest.mark.asyncio
async def test_crash_returns_run_failed_crash(tmp_path: Path) -> None:
    """A FunctionAction that raises RuntimeError -> RunFailed(CRASH),
    does NOT raise; terminal event RUN_FAILED."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    result = await _run_resolver_plan(
        _plan_with_raising_action("boom"),
        run_id="run-crash",
        artifacts_dir=artifacts_dir,
        crash=True,
    )

    assert isinstance(result, RunFailed)
    assert result.error_kind is FailureKind.CRASH
    assert result.error_type == "RuntimeError"
    assert "boom" in result.message
    types = _lifecycle_types(artifacts_dir / "run-crash")
    assert LifecycleEvent.RUN_FAILED.value in types
