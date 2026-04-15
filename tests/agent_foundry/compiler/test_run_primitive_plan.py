"""Task G.2: end-to-end tests for the async ``run_primitive_plan`` entry point.

The async entry point builds an ``AgentRunContext`` from explicit
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
from agent_foundry.orchestration.errors import AgentFailedError
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.primitives.models import (
    AgentAction,
    ContainerReusePolicy,
    FunctionAction,
    Sequence,
)
from agent_foundry.primitives.plan import PrimitivePlan
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
    """Install a scripted driver via the ``set_driver_factory`` seam.

    Returns a callable that takes a ``FakeClaudeCodeDriver`` and wires
    it for the duration of the test. Teardown resets the seam.
    """

    installed: list[None] = []

    def _install(driver: FakeClaudeCodeDriver) -> None:
        container_executor.set_driver_factory(lambda live, schema: driver)
        installed.append(None)

    yield _install

    if installed:
        container_executor.set_driver_factory(None)


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
    ) -> None:
        real_init(
            self,
            workspace_volume=workspace_volume,
            base_image_tag=base_image_tag,
            docker_client_factory=docker_client_factory,
            manager=manager or fake_manager,
        )

    monkeypatch.setattr(registry_mod.AgentContainerRegistry, "__init__", _patched_init)
    return fake_manager


# --- Primitive builders -----------------------------------------------------


def _agent_primitive() -> AgentAction:
    return AgentAction[PlanInput, AgentOut](
        prompt_builder=lambda s: f"do: {s.task}",
        instructions_provider=lambda: "instructions",
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
    from agent_foundry.compiler.primitive_compiler import run_primitive_plan

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

    assert isinstance(result, PlanOutput)
    assert result.x == 2

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
    from agent_foundry.compiler.primitive_compiler import run_primitive_plan

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
    from agent_foundry.compiler.primitive_compiler import run_primitive_plan

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
    from agent_foundry.compiler.primitive_compiler import run_primitive_plan
    from agent_foundry.orchestration import registry as registry_mod
    from agent_foundry.orchestration.run_context import current_run_context

    driver = FakeClaudeCodeDriver(turn_script=[_success_env(x=1)])
    install_driver(driver)

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    # Set the run_ctx.cancel_event at registry get_or_create time — this
    # is the first executor touchpoint after run_primitive_plan has set
    # the current_run_context ContextVar. The executor's pre-turn check
    # then sees a set event and raises AgentFailedError("cancelled").
    real_get = registry_mod.AgentContainerRegistry.get_or_create

    async def _cancelling_get(self, primitive, *, lifecycle_writer, agent_name):
        live = await real_get(
            self, primitive, lifecycle_writer=lifecycle_writer, agent_name=agent_name
        )
        ctx = current_run_context.get()
        if ctx is not None:
            ctx.cancel_event.set()
        return live

    monkeypatch.setattr(registry_mod.AgentContainerRegistry, "get_or_create", _cancelling_get)

    with pytest.raises(AgentFailedError, match="cancelled"):
        await run_primitive_plan(
            _plan_sequence(),
            initial_state=PlanInput(task="hi"),
            artifacts_dir=artifacts_dir,
            workspace_volume="vol",
            base_image_tag="base:test",
            responder_provider=static_provider(FakeResponder(answers=[])),
            run_id="run-cancel",
        )

    run_dir = artifacts_dir / "run-cancel"
    # Summary still written even after cancel.
    assert (run_dir / "summary.txt").is_file()
    # Registry shutdown happened — every container the fake created was
    # destroyed.
    assert patch_registry_manager.destroyed_ids, (
        "shutdown_all should destroy at least one container on cancel path"
    )


@pytest.mark.asyncio
async def test_exception_mid_run_propagates_and_cleans_up(
    tmp_path: Path,
    install_driver,
    patch_registry_manager,
):
    """Executor raises (FailureOutcome) → AgentFailedError propagates;
    teardown still runs: registry destroyed + summary.txt written.
    """
    from agent_foundry.compiler.primitive_compiler import run_primitive_plan

    driver = FakeClaudeCodeDriver(turn_script=[_failure_env("boom")])
    install_driver(driver)

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    with pytest.raises(AgentFailedError):
        await run_primitive_plan(
            _plan_sequence(),
            initial_state=PlanInput(task="hi"),
            artifacts_dir=artifacts_dir,
            workspace_volume="vol",
            base_image_tag="base:test",
            responder_provider=static_provider(FakeResponder(answers=[])),
            run_id="run-fail",
        )

    run_dir = artifacts_dir / "run-fail"
    assert (run_dir / "summary.txt").is_file()
    assert patch_registry_manager.destroyed_ids, (
        "shutdown_all should destroy containers even on failure path"
    )
