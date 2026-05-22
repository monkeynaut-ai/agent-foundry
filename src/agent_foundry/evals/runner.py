"""Eval suite runner.

The runner orchestrates ``N x cases`` invocations of a task function
against a Pydantic Evals ``Dataset`` and assembles a typed
:class:`RunResult`.

The runner is decoupled from target invocation: callers supply the
task function. Two task builders are provided:

- :func:`build_run_primitive_plan_task` — for :class:`AgentAction`
  targets. Wraps the full container-backed orchestration path.
- :func:`build_invoke_ai_call_task` — for :class:`AICall` targets.
  Wraps :func:`invoke_ai_call`. No container, no ``RunContext``, no
  responder.

Tests can supply any async callable in place of these builders.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent_foundry.ai_models.execute.invoke import invoke_ai_call
from agent_foundry.evals.models import EvalSuite, RunResult
from agent_foundry.evals.responder import RaiseOnInvokeResponder
from agent_foundry.primitives.ai_call import AICall
from agent_foundry.primitives.models import AgentAction
from agent_foundry.primitives.plan import PrimitivePlan

# Mirror Pydantic Evals' permissive task signature — case input/output
# types are dataset-bound at runtime, not statically checked here.
type Task = Callable[[Any], Awaitable[Any]]


async def run_suite(
    suite: EvalSuite,
    *,
    task: Task,
    max_concurrency: int = 1,
) -> RunResult:
    """Execute ``suite`` and return a :class:`RunResult`.

    The dataset is evaluated once with ``repeat=invocations_per_case``,
    which Pydantic Evals expands into ``cases x N`` runs in a single
    concurrent batch. The returned report contains one entry per
    ``(case, invocation)`` pair (named ``"<case> [i/N]"``).

    ``max_concurrency`` is forwarded to Pydantic Evals' ``Dataset.evaluate``
    and controls how many ``(case, invocation)`` pairs run in parallel.
    Default 1 (sequential) until concurrent agent invocations are
    verified safe — see design doc.
    """
    started_at = datetime.now(UTC)
    run_id = _generate_run_id(started_at)

    report = await suite.dataset.evaluate(
        task,
        repeat=suite.invocations_per_case,
        max_concurrency=max_concurrency,
        progress=False,
    )

    ended_at = datetime.now(UTC)

    return RunResult(
        run_id=run_id,
        suite_name=suite.name,
        started_at=started_at,
        ended_at=ended_at,
        invocations_per_case=suite.invocations_per_case,
        report=report,
    )


def build_run_primitive_plan_task(
    agent: AgentAction,
    *,
    artifacts_dir: Path,
    workspace_volume: str,
    base_image_tag: str,
) -> Task:
    """Build a task function that invokes ``agent`` via ``run_primitive_plan``.

    Wraps the agent in a :class:`PrimitivePlan` and delegates to Agent
    Foundry's orchestration entry point. The eval-strict
    :class:`RaiseOnInvokeResponder` is installed; a case that triggers
    a responder interaction raises and surfaces as a per-case failure
    in Pydantic Evals' report.
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
    """Build a task function that invokes ``call`` via ``invoke_ai_call``.

    No container, no ``RunContext``, no responder — the task is a
    direct call into the AICall's resolved fields and configured
    provider. Each task call performs one inference.
    """

    async def task(input_state: Any) -> BaseModel:
        return await invoke_ai_call(call, input_state)

    return task


def _generate_run_id(started_at: datetime) -> str:
    """Generate a run identifier that sorts naturally and avoids collisions."""
    stamp = started_at.strftime("%Y%m%dT%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"{stamp}_{suffix}"
