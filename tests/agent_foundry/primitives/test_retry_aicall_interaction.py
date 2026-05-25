"""Interaction test — AC I1.

Verifies that Capability A (Retry exception policy) and Capability B
(AICall executor) compose correctly with no implicit coupling beyond the
call-order semantics described in the feature definition.

Scenario:
    Retry[
        body = Sequence[ai_call_with_catching_executor, fallible_fn_action],
        exception_policy = CATCH_AND_CONTINUE,
        max_attempts = 3,
        until = lambda s: s.verdict == "ok",
    ]

  I1-a: The AICall's executor catches an underlying inference exception and
        returns a synthesized verdict. The Retry exception policy does NOT fire
        for this path — no AttemptFailure is recorded, no RETRY_ATTEMPT_FAILED
        event is emitted for the AICall step.

  I1-b: The FunctionAction raises on attempt 1. The Retry exception policy
        fires — RETRY_ATTEMPT_FAILED is emitted, state is rolled back, and the
        next attempt succeeds.

  I1-c: Both behaviours hold together. Final verdict == "ok". Exactly one
        RETRY_ATTEMPT_FAILED event in the lifecycle stream (from the
        FunctionAction, not from the AICall).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.ai_models.inference import (
    InferenceParameters,
    InferenceProvider,
    InferenceRequest,
)
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.compiler.primitive_compiler import compile_runtime_plan
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.lifecycle_writer import LifecycleWriter
from agent_foundry.primitives.ai_call import AICall, ModelInput
from agent_foundry.primitives.models import FunctionAction, Retry, RetryExceptionPolicy, Sequence
from agent_foundry.primitives.plan import PrimitivePlan

# ---------------------------------------------------------------------------
# State model
# ---------------------------------------------------------------------------


class _ReviewState(BaseModel):
    verdict: str = "pending"
    attempt_count: int = 0
    fn_succeeded: bool = False


# ---------------------------------------------------------------------------
# Capturing lifecycle writer
# ---------------------------------------------------------------------------


@dataclass
class _CapturingWriter(LifecycleWriter):
    events: list[dict] = field(default_factory=list)

    def append(self, event_type: LifecycleEvent, **fields: Any) -> None:
        self.events.append({"type": event_type, **fields})

    def append_run_event(self, kind: str, **fields: Any) -> None:
        pass

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Provider that always raises — used to prove the executor's catch fires
# ---------------------------------------------------------------------------


class _RaisingProvider(InferenceProvider):
    def __init__(self) -> None:
        self.call_count = 0

    async def __call__(self, request: InferenceRequest) -> BaseModel:
        self.call_count += 1
        raise ValueError(f"provider unavailable (call #{self.call_count})")

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixture: build the workflow
# ---------------------------------------------------------------------------


@pytest.fixture()
def _workflow():
    raising_provider = _RaisingProvider()
    model_entry = ModelEntry(
        model_id="fake",
        provider=raising_provider,
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )

    # AICall executor: calls the raising provider, catches ValueError,
    # returns a synthesized "fallback" verdict. This verifies I1-a.
    executor_calls: list[dict] = []

    async def catching_executor(*, primitive: Any, model_input: Any) -> _ReviewState:
        executor_calls.append({"model_input": model_input})
        try:
            # Deliberately call the underlying provider via its model_entry —
            # the provider raises, proving the catch branch is exercised.
            from agent_foundry.ai_models.inference import InferenceRequest

            req = InferenceRequest(
                model_id=model_entry.model_id,
                instructions="sys",
                prompt="usr",
                parameters=InferenceParameters(max_tokens=16),
                output_type=_ReviewState,
            )
            return await model_entry.provider(req)  # type: ignore[return-value]
        except ValueError:
            # Synthesize a non-passing verdict — Retry's until() will see this
            # and continue (or the FunctionAction will succeed and change verdict).
            return _ReviewState(verdict="fallback", attempt_count=model_input.attempt_count)

    ai_call = AICall[_ReviewState, _ReviewState](
        model_input=ModelInput[_ReviewState](instructions="sys", prompt="usr"),
        parameters=InferenceParameters(max_tokens=16),
        model=model_entry,
        executor=catching_executor,
    )

    # FunctionAction: raises on attempt 1, succeeds with verdict="ok" on attempt 2.
    fn_call_count = {"n": 0}

    def fallible_fn(s: _ReviewState) -> _ReviewState:
        fn_call_count["n"] += 1
        if fn_call_count["n"] == 1:
            raise RuntimeError("fn transient failure")
        return _ReviewState(
            verdict="ok",
            attempt_count=s.attempt_count + 1,
            fn_succeeded=True,
        )

    fn_action = FunctionAction[_ReviewState, _ReviewState](function=fallible_fn)

    body = Sequence[_ReviewState, _ReviewState](steps=[ai_call, fn_action])

    retry = Retry[_ReviewState, _ReviewState](
        max_attempts=3,
        until=lambda s: s.verdict == "ok",
        body=body,
        exception_policy=RetryExceptionPolicy.CATCH_AND_CONTINUE,
    )

    return {
        "retry": retry,
        "raising_provider": raising_provider,
        "executor_calls": executor_calls,
        "fn_call_count": fn_call_count,
    }


# ---------------------------------------------------------------------------
# Run helper
# ---------------------------------------------------------------------------


async def _run(retry: Retry, writer: _CapturingWriter) -> _ReviewState:
    from agent_foundry.orchestration.run_context import (
        RunContext,
        current_run_context,
    )

    ctx = RunContext(
        run_id="interaction-test",
        artifacts_dir=__import__("pathlib").Path(__import__("tempfile").mkdtemp()),
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=writer,
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    token = current_run_context.set(ctx)
    try:
        plan = PrimitivePlan(root=retry)
        graph = compile_runtime_plan(plan)
        result = await graph.ainvoke(_ReviewState().model_dump())
        return _ReviewState.model_validate(result)
    finally:
        current_run_context.reset(token)


# ---------------------------------------------------------------------------
# I1 — composite interaction test
# ---------------------------------------------------------------------------


class TestRetryAICallInteraction:
    @pytest.mark.asyncio
    async def test_i1_composite(self, _workflow: dict) -> None:
        """I1: AICall executor swallows inference exception; FunctionAction triggers Retry policy.

        I1-a: The AICall's executor catches ValueError from the raising provider and
              returns a synthesized _ReviewState. The Retry policy does NOT fire for
              the AICall step — the Sequence body raises only when the FunctionAction raises.

        I1-b: On attempt 1, the FunctionAction raises RuntimeError. The Retry policy
              fires: RETRY_ATTEMPT_FAILED is emitted, state is rolled back. On attempt
              2 the FunctionAction succeeds with verdict="ok".

        I1-c: Final verdict == "ok". Exactly one RETRY_ATTEMPT_FAILED event (from the
              FunctionAction, not the AICall). The AICall executor was called on both
              attempts (once when the FunctionAction failed, once when it succeeded).
        """
        writer = _CapturingWriter()
        result = await _run(_workflow["retry"], writer)

        # I1-c: workflow completes successfully
        assert result.verdict == "ok"
        assert result.fn_succeeded is True

        # I1-b: exactly one RETRY_ATTEMPT_FAILED event — from the FunctionAction raise
        failed_events = [
            e for e in writer.events if e["type"] == LifecycleEvent.RETRY_ATTEMPT_FAILED
        ]
        assert len(failed_events) == 1
        assert failed_events[0]["exception_type"] == "RuntimeError"
        assert failed_events[0]["attempt_num"] == 1

        # I1-a: AICall executor was called on both attempts (attempt 1 where fn failed,
        #        attempt 2 where fn succeeded). The raising provider was called the same
        #        number of times, proving the catch branch fired each time.
        executor_calls = _workflow["executor_calls"]
        raising_provider: _RaisingProvider = _workflow["raising_provider"]

        assert len(executor_calls) == 2
        assert raising_provider.call_count == 2  # provider raised both times; executor caught both

        # I1-a: no RETRY_ATTEMPT_FAILED event has exception_type matching a provider error —
        #        the AICall executor swallowed ValueError; only RuntimeError from fn_action reached Retry.
        for ev in failed_events:
            assert ev["exception_type"] != "ValueError", (
                "ValueError from the AICall's provider must not reach Retry policy"
            )
