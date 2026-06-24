"""Tests for AgentAction.timeout_seconds enforcement (issue #80).

The compiler wraps an async AgentAction executor in a per-turn deadline derived
from ``AgentAction.timeout_seconds`` and raises ``ConstructTimeoutError`` when
exceeded. Sync executors cannot be cancelled mid-flight and are not
deadline-enforced (documented limitation; the default container executor is
async).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.compiler.compiler import compile_process
from agent_foundry.constructs.errors import ConstructTimeoutError
from agent_foundry.constructs.models import AgentAction, ContainerReusePolicy
from agent_foundry.constructs.process import Process


class AgentInput(BaseModel):
    query: str


class AgentOutput(BaseModel):
    answer: str


def _stub_prompt(state: AgentInput) -> str:
    return f"Q: {state.query}"


def _stub_instructions(_state: object) -> str:
    return "instructions"


def _make_action(*, executor: Any, timeout_seconds: int = 3600) -> AgentAction:
    return AgentAction[AgentInput, AgentOutput](
        name="test-agent",
        model="claude-sonnet-4-6",
        prompt_builder=_stub_prompt,
        instructions_provider=_stub_instructions,
        executor=executor,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
        timeout_seconds=timeout_seconds,
    )


@pytest.fixture(autouse=True)
def _run_ctx(tmp_path: Any) -> Any:
    from agent_foundry.orchestration.run_context import (
        NoOpLifecycleWriter,
        RunContext,
        current_run_context,
    )

    ctx = RunContext(
        run_id="agent-timeout-test",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    token = current_run_context.set(ctx)
    yield
    current_run_context.reset(token)


class TestAsyncExecutorTimeout:
    def test_slow_async_executor_times_out(self) -> None:
        async def slow_executor(*, construct, prompt, instructions, run_ctx) -> AgentOutput:
            await asyncio.sleep(30)
            return AgentOutput(answer="too-late")

        action = _make_action(executor=slow_executor, timeout_seconds=1)
        graph = compile_process(Process(action))

        with pytest.raises(ConstructTimeoutError):
            asyncio.run(graph.ainvoke({"query": "x"}))

    def test_fast_async_executor_not_affected(self) -> None:
        async def fast_executor(*, construct, prompt, instructions, run_ctx) -> AgentOutput:
            return AgentOutput(answer="quick")

        action = _make_action(executor=fast_executor, timeout_seconds=30)
        graph = compile_process(Process(action))

        result = asyncio.run(graph.ainvoke({"query": "x"}))
        assert result["answer"] == "quick"


class TestSyncExecutorNotEnforced:
    """Sync executors run to completion — synchronous code cannot be cancelled,
    so the deadline does not apply (the default container executor is async)."""

    def test_sync_executor_runs_past_deadline(self) -> None:
        def slow_sync_executor(*, construct, prompt, instructions, run_ctx) -> AgentOutput:
            time.sleep(1.1)
            return AgentOutput(answer="done")

        action = _make_action(executor=slow_sync_executor, timeout_seconds=1)
        graph = compile_process(Process(action))

        result = asyncio.run(graph.ainvoke({"query": "x"}))
        assert result["answer"] == "done"
