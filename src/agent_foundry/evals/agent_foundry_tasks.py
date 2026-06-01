"""Task builders — bind a target to the inputs it expects.

A runner is target-agnostic: it dispatches ``Task`` callables against
each case's input. The task is what knows how to invoke the specific
target (an :class:`AgentAction` via containerized orchestration, an
:class:`AICall` via direct inference, future kinds via their own
mechanisms).

The CLI and the API server use these builders to materialize the
appropriate :class:`Task` for a suite's target kind, then hand the
task to the runner.

Agent-target builds also install :class:`RaiseOnInvokeResponder`,
which forces eval cases to fail loudly rather than auto-answer
clarification requests — auto-answering would make outcomes
non-deterministic and obscure the variable under test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent_foundry.evals.models import Task
from agent_foundry.primitives.ai_call import AICall
from agent_foundry.primitives.models import AgentAction
from agent_foundry.primitives.plan import PrimitivePlan
from agent_foundry.responders.models import (
    ResponderContext,
    ResponderRequest,
    ResponderResponse,
)
from agent_foundry.responders.protocol import Responder


class EvalResponderInvokedError(RuntimeError):
    """Raised when an agent under eval triggers a responder interaction."""


class EvalRunNotCompletedError(RuntimeError):
    """Raised when an eval run ends aborted or failed.

    The Inspect ``Task`` contract is exception-based; an eval case that
    does not complete must surface as a per-case failure, so the
    non-completed ``RunOutcome`` is re-introduced as an exception here.
    """


class RaiseOnInvokeResponder(Responder):
    """Responder that raises on every invocation.

    Plugs into :func:`agent_foundry.orchestration.runner.run_primitive_plan`
    via :func:`agent_foundry.responders.protocol.static_provider`.
    """

    async def respond(
        self, request: ResponderRequest, context: ResponderContext
    ) -> ResponderResponse:
        raise EvalResponderInvokedError(
            "Responder invoked during eval — single-agent eval cases must run "
            "to completion without interactions. "
            f"agent={context.agent_name!r} invocation={context.invocation} "
            f"turn={context.turn} request_kind={request.kind}"
        )


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

    ``run_primitive_plan`` returns a ``RunOutcome``; the Inspect ``Task``
    contract is exception-based, so a completed run unwraps to its
    product output and a failed or aborted run raises.
    """
    # Deferred imports — orchestration pulls in heavy dependencies
    # (Docker SDK, telemetry) that we don't want at import time.
    from agent_foundry.orchestration import runner as runner_mod
    from agent_foundry.orchestration.run_outcome import (
        RunAborted,
        RunCompleted,
        RunFailed,
    )
    from agent_foundry.responders.protocol import static_provider

    plan = PrimitivePlan(root=agent)
    responder_provider = static_provider(RaiseOnInvokeResponder())

    async def task(input_state: Any) -> BaseModel:
        outcome = await runner_mod.run_primitive_plan(
            plan,
            initial_state=input_state,
            artifacts_dir=artifacts_dir,
            workspace_volume=workspace_volume,
            base_image_tag=base_image_tag,
            responder_provider=responder_provider,
        )
        if isinstance(outcome, RunCompleted):
            return outcome.output
        if isinstance(outcome, RunAborted):
            raise EvalRunNotCompletedError(f"run aborted: {outcome.reason}")
        if isinstance(outcome, RunFailed):
            raise EvalRunNotCompletedError(
                f"run failed ({outcome.error_kind.value}): {outcome.error_type}: {outcome.message}"
            )
        raise EvalRunNotCompletedError(f"unexpected run outcome: {outcome!r}")

    return task


def build_invoke_ai_call_task(call: AICall) -> Task:
    """Build a task that invokes ``call`` via its configured executor.

    When ``call.executor`` is None, falls back to ``invoke_ai_call``.
    When ``call.executor`` is set, the custom executor runs instead —
    consistent with how the compiler dispatches the same AICall. No
    container, no ``RunContext``, no responder.
    """
    import inspect as _inspect

    executor = call.executor
    # Check the instance and its __call__ method — handles both async def functions
    # and callable classes with an async __call__.
    executor_is_async = executor is not None and (
        _inspect.iscoroutinefunction(executor)
        or _inspect.iscoroutinefunction(getattr(type(executor), "__call__", None))  # noqa: B004
    )

    async def task(input_state: Any) -> BaseModel:
        if executor is None:
            from agent_foundry.ai_models.execute.invoke import invoke_ai_call

            return await invoke_ai_call(primitive=call, model_input=input_state)
        if executor_is_async:
            return await executor(primitive=call, model_input=input_state)
        return executor(primitive=call, model_input=input_state)  # type: ignore[return-value]

    return task
