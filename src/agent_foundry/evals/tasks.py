"""Task builders — bind a target to the inputs it expects.

A runner is target-agnostic: it dispatches ``Task`` callables against
each case's input. The task is what knows how to invoke the specific
target (an :class:`AgentAction` via containerized orchestration, an
:class:`AICall` via direct inference, future kinds via their own
mechanisms).

The CLI and the API server use these builders to materialize the
appropriate :class:`Task` for a suite's target kind, then hand the
task to the runner.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent_foundry.ai_models.execute.invoke import invoke_ai_call
from agent_foundry.evals.models import Task
from agent_foundry.evals.responder import RaiseOnInvokeResponder
from agent_foundry.primitives.ai_call import AICall
from agent_foundry.primitives.models import AgentAction
from agent_foundry.primitives.plan import PrimitivePlan


def build_run_primitive_plan_task(
    agent: AgentAction,
    *,
    artifacts_dir: Path,
    workspace_volume: str,
    base_image_tag: str,
) -> Task:
    """Build a task that invokes ``agent`` via ``run_primitive_plan``.

    Wraps the agent in a :class:`PrimitivePlan` and delegates to Agent
    Foundry's orchestration entry point. The eval-strict
    :class:`RaiseOnInvokeResponder` is installed; a case that triggers
    a responder interaction raises and surfaces as a per-case failure
    in the runner's report.
    """
    # Deferred imports — orchestration pulls in heavy dependencies
    # (Docker SDK, telemetry) that we don't want at import time.
    from agent_foundry.orchestration.runner import run_primitive_plan
    from agent_foundry.responders.protocol import static_provider

    plan = PrimitivePlan(root=agent)
    responder_provider = static_provider(RaiseOnInvokeResponder())

    async def task(input_state: Any) -> BaseModel:
        return await run_primitive_plan(
            plan,
            initial_state=input_state,
            artifacts_dir=artifacts_dir,
            workspace_volume=workspace_volume,
            base_image_tag=base_image_tag,
            responder_provider=responder_provider,
        )

    return task


def build_invoke_ai_call_task(call: AICall) -> Task:
    """Build a task that invokes ``call`` via ``invoke_ai_call``.

    No container, no ``RunContext``, no responder — the task is a
    direct call into the AICall's resolved fields and configured
    provider. Each task call performs one inference.
    """

    async def task(input_state: Any) -> BaseModel:
        return await invoke_ai_call(call, input_state)

    return task
