# Implementation Plan: Failure Resilience — Retry Exception Policy & AICall Executor

Feature definition: `docs/archipelago/failure-resilience-retry-aicall-feature-def.md`
Design: Design 2 (Revised) — StrEnum policy + `on_exhaustion` hook + configurable AICall executor

## Dependency order

```
Task 1 ──► Task 2 ──► Task 6 ──► Task 7
Task 3  ──────────────────────────────►
Task 4 ──► Task 5 ──► Task 5.5 ──────►
```

Tasks 1, 3, and 4 are independent of each other and can start in parallel.
Task 6 depends on Tasks 1, 2, and 3. Tasks 5 and 5.5 depend on Task 4. Task 7 depends on Tasks 5.5 and 6.

---

## Task 1 — Retry types module

**Scope:** Create `src/agent_foundry/primitives/retry_types.py` with the three new data types.

**Files touched:**
- `src/agent_foundry/primitives/retry_types.py` (new)
- `tests/agent_foundry/primitives/test_retry_types.py` (new)

**TDD steps:**

Write `test_retry_types.py` first. Red cases:
- `RetryExhaustionReason` is a `StrEnum` with exactly three members:
  - `CONDITION_NOT_MET = "condition_not_met"` — no exceptions; `until()` never returned True
  - `BODY_EXCEPTIONS = "body_exceptions"` — every attempt raised under opt-in policy
  - `MIXED = "mixed"` — at least one attempt raised AND at least one completed normally with `until()` False
- `AttemptFailure` validates required fields: `attempt_num: int`, `exception_type: str`, `exception_message: str`, `timestamp: datetime`
- `RetryExhaustion` validates `max_attempts`, `reason`, `attempt_failures`, `last_state`
- `RetryExhaustion.last_state` accepts any `BaseModel` subclass (no `arbitrary_types_allowed` needed — `I: BaseModel` is natively supported by Pydantic)
- `RetryExhaustion` with each `RetryExhaustionReason` roundtrips correctly

Then implement:

```python
# src/agent_foundry/primitives/retry_types.py
"""Types for Retry exhaustion reporting passed to the on_exhaustion hook."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RetryExhaustionReason(StrEnum):
    """Why a Retry primitive exhausted all attempts without until() returning True.

    - CONDITION_NOT_MET: all attempts ran to completion; until() never returned True.
    - BODY_EXCEPTIONS: every attempt raised under the TREAT_AS_FAILURE policy;
      no attempt completed normally.
    - MIXED: at least one attempt raised (and was tolerated under TREAT_AS_FAILURE)
      and at least one attempt completed normally with until() returning False.
    """

    CONDITION_NOT_MET = "condition_not_met"
    BODY_EXCEPTIONS   = "body_exceptions"
    MIXED             = "mixed"


class AttemptFailure(BaseModel):
    attempt_num: int
    exception_type: str
    exception_message: str
    timestamp: datetime


class RetryExhaustion[I: BaseModel](BaseModel):
    """Passed to Retry.on_exhaustion when all attempts are consumed.

    ``last_state`` is the accumulated state at the moment of exhaustion —
    specifically, the state after all rollbacks complete. Under
    ``BODY_EXCEPTIONS`` where every attempt raised, this equals the pre-Retry
    input state (no body output was ever committed). Under ``CONDITION_NOT_MET``
    or ``MIXED``, it reflects the output of the last completed body attempt.
    Handlers must not assume ``last_state`` always reflects a body's output.
    """

    max_attempts: int
    reason: RetryExhaustionReason
    attempt_failures: list[AttemptFailure] = Field(default_factory=list)
    last_state: I
```

**Verify:** `pdm test-unit tests/agent_foundry/primitives/test_retry_types.py` — all green.

---

## Task 2 — Retry model fields

**Scope:** Add `RetryExceptionPolicy` enum and two new fields to `Retry` in `models.py`.

**Files touched:**
- `src/agent_foundry/primitives/models.py`
- `tests/agent_foundry/primitives/test_primitive_models.py` (extend)

**TDD steps:**

Extend `test_primitive_models.py` with a `TestRetryExceptionPolicy` class. Red cases:
- `RetryExceptionPolicy` is a `StrEnum` with `PROPAGATE = "propagate"` and `TREAT_AS_FAILURE = "treat_as_failure"`
- `Retry` constructed without new fields has `exception_policy == RetryExceptionPolicy.PROPAGATE` and `on_exhaustion is None`
- `Retry` accepts `exception_policy=RetryExceptionPolicy.TREAT_AS_FAILURE`
- `Retry` accepts a sync `on_exhaustion` callable
- `Retry` accepts an async `on_exhaustion` callable
- All existing `Retry` model tests still pass (backward compat — AC A6)

Then implement in `models.py`:

1. Add `RetryExceptionPolicy(StrEnum)` after `ContainerReusePolicy`:
```python
class RetryExceptionPolicy(StrEnum):
    """Controls what Retry does when its body raises an exception.

    - PROPAGATE: re-raise immediately (default, preserves existing behaviour).
    - TREAT_AS_FAILURE: consume the attempt, restore pre-attempt state,
      continue to the next attempt as if the body returned an unmet condition.
    """

    PROPAGATE        = "propagate"
    TREAT_AS_FAILURE = "treat_as_failure"
```

2. Add two fields to `Retry`:
```python
exception_policy: RetryExceptionPolicy = RetryExceptionPolicy.PROPAGATE
"""Exception handling policy for body failures. Defaults to PROPAGATE (existing behaviour)."""

on_exhaustion: Callable[..., O | Awaitable[O]] | None = None
"""Optional hook called when all attempts are consumed without until() returning True.

Receives a ``RetryExhaustion`` instance. May be sync or async. When None,
Retry exits silently with the current accumulated state (today's behaviour).
When set, its return value (an instance of ``O``) replaces the accumulated
state, enabling the parent Conditional to route on a structured failure output.
"""
```

3. Import `RetryExhaustion` for type annotation (TYPE_CHECKING guard to avoid runtime circular):
```python
from __future__ import annotations  # already present
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from agent_foundry.primitives.retry_types import RetryExhaustion  # noqa: F401
```

**Verify:** `pdm test-unit tests/agent_foundry/primitives/test_primitive_models.py` — all green.

---

## Task 3 — LifecycleEvent: RETRY_ATTEMPT_FAILED

**Scope:** Add one event constant to the `LifecycleEvent` enum.

**Files touched:**
- `src/agent_foundry/orchestration/lifecycle_events.py`
- `tests/agent_foundry/orchestration/test_lifecycle_events.py` (new or extend)

**TDD steps:**

Write/extend the test. Red cases:
- `LifecycleEvent.RETRY_ATTEMPT_FAILED == "retry_attempt_failed"`
- `LifecycleEvent.RETRY_ATTEMPT_FAILED` is a member of `LifecycleEvent`

Then add to the enum after `FUNCTION_ACTION_FAILED` (grouped with action-level failures):
```python
RETRY_ATTEMPT_FAILED = "retry_attempt_failed"
```

**Verify:** `pdm test-unit` — all green.

---

## Task 4 — AICall executor field + invoke_ai_call parameter rename

**Scope:** Add `executor` field to `AICall` and rename `invoke_ai_call`'s parameters so that the default and custom executor calling conventions are consistent.

The current signature `invoke_ai_call(req, input_state)` uses names that don't match the new executor contract `(*, primitive, model_input)`. A consumer wrapping `invoke_ai_call` would call `invoke_ai_call(primitive=primitive, model_input=model_input)` — which fails silently with the old param names. Renaming to `primitive` and `model_input` fixes this without breaking any positional callers.

**Files touched:**
- `src/agent_foundry/primitives/ai_call.py`
- `src/agent_foundry/ai_models/execute/invoke.py`
- `tests/agent_foundry/compiler/test_ai_call_compiler.py` (extend — model-level tests)
- `tests/agent_foundry/ai_models/execute/test_invoke.py` (update param names in any keyword call sites)

**TDD steps:**

Step A — `invoke_ai_call` rename:
- Check `tests/agent_foundry/ai_models/execute/test_invoke.py` for keyword call sites; update `req=` → `primitive=`, `input_state=` → `model_input=` where present.
- Rename in `invoke.py`: `req: AICall[I, O]` → `primitive: AICall[I, O]`, `input_state: I` → `model_input: I`. All internal usages of those names follow. Positional callers (`invoke_ai_call(action, model_input)`) are unaffected.
- Update the single call in `primitive_compiler.py` from `invoke_ai_call(action, model_input)` to `invoke_ai_call(primitive=action, model_input=model_input)` to make both paths use keyword form consistently.
- Update the call in `evals/agent_foundry_tasks.py` from `invoke_ai_call(call, input_state)` to `invoke_ai_call(primitive=call, model_input=input_state)`.

Step B — `AICall.executor` field:
- Write model-level tests (red): `AICall` without `executor` has `executor is None`; accepts sync callable; accepts async callable; all existing tests pass.
- Add to `ai_call.py`:
```python
from collections.abc import Awaitable  # add to existing import

# In AICall:
executor: Callable[..., O | Awaitable[O]] | None = None
"""Callable that performs the inference call. When None, the compiler uses
``invoke_ai_call`` (the default LLM provider path). Pass a custom callable to
mock inference in tests, wrap with metrics, swap backends, or synthesize
fallback verdicts on exception.

Contract: ``(*, primitive: AICall[I, O], model_input: I) -> O | Awaitable[O]``.
Matches ``invoke_ai_call``'s keyword parameter names so consumers can wrap it
directly: ``return await invoke_ai_call(primitive=primitive, model_input=model_input)``.
Both sync and async callables are accepted; the compiler detects the variant
at compile time.
"""
```

**Verify:**
- `pdm test-unit tests/agent_foundry/compiler/test_ai_call_compiler.py` — all green
- `pdm test-unit tests/agent_foundry/ai_models/execute/test_invoke.py` — all green

---

## Task 5 — `_compile_ai_call` executor dispatch (Capability B)

**Scope:** Replace the hard-coded `invoke_ai_call` call with executor dispatch mirroring `_compile_agent_action`. Hoist `RetryExceptionPolicy` import to module-level (F4, needed here as a reminder for Task 6).

**Files touched:**
- `src/agent_foundry/compiler/primitive_compiler.py`
- `tests/agent_foundry/compiler/test_ai_call_executor.py` (new)

**TDD steps:**

Write `test_ai_call_executor.py` covering AC B1–B5 (B6 is covered in Task 5.5):

```
B1. executor=None (default) → invoke_ai_call runs; existing behaviour unchanged
    (verified by checking that a _CapturingProvider receives the InferenceRequest)
B2. Sync custom executor → called with keyword args (primitive=action, model_input=...);
    return value used as AICall output
B3. Async custom executor → awaited; result used as AICall output
B4. Custom executor returns wrong type → PrimitiveCompilationError raised
B5. Custom executor catches its own underlying exception and returns synthesized O →
    AICall output is the synthesized value; no exception visible to the caller
```

Test helpers:
- `_spy_executor(output)` — sync callable; records (primitive, model_input) calls; returns fixed `O`
- `_async_spy_executor(output)` — async version
- `_raising_executor(exc)` — raises given exception; used in B5 within a wrapping executor
- `_catching_executor(inner_exc, fallback_output)` — calls a sub-callable that raises, catches it, returns `fallback_output`

Then update `_compile_ai_call`:

```python
def _compile_ai_call(
    graph: StateGraph,
    action: AICall,
    ctx: CompileContext,
) -> CompileResult:
    import inspect as _inspect

    node_id = ctx.prefix
    input_type, output_type = get_type_args(action)

    executor = action.executor
    executor_is_async = executor is not None and _inspect.iscoroutinefunction(executor)

    def _validate_typed(result: Any) -> BaseModel:
        if not isinstance(result, output_type):
            raise PrimitiveCompilationError(
                f"AICall {node_id}: executor returned "
                f"{type(result).__name__}, expected {output_type.__name__}",
                primitive_type=node_id,
            )
        return result

    async def node_fn(state: dict[str, Any]) -> dict[str, Any]:
        from agent_foundry.orchestration.run_context import current_run_context

        model_input = _validate_scoped_input(state, input_type, node_id)

        ctx_opt = current_run_context.get()
        redaction = (
            ctx_opt.telemetry.redaction
            if ctx_opt is not None and ctx_opt.telemetry is not None
            else None
        )
        run_id = ctx_opt.run_id if ctx_opt is not None else node_id

        with emit_span(
            name=f"agent_foundry.AICall.{node_id}",
            primitive_type="AICall",
            primitive_name=node_id,
            input_model=model_input,
            run_id=run_id,
            redaction=redaction,
        ) as handle:
            handle.set_operation_name("chat")
            try:
                if executor is None:
                    from agent_foundry.ai_models.execute.invoke import invoke_ai_call
                    result = await invoke_ai_call(primitive=action, model_input=model_input)
                elif executor_is_async:
                    result = await executor(primitive=action, model_input=model_input)
                else:
                    result = executor(primitive=action, model_input=model_input)
            except TypeError as exc:
                raise PrimitiveCompilationError(
                    f"AICall {node_id}: {exc}",
                    primitive_type=node_id,
                ) from exc
            typed = _validate_typed(result)
            handle.set_output(typed)
            return typed.model_dump()

    graph.add_node(node_id, node_fn)
    return CompileResult(node_id, node_id)
```

Also add `RetryExceptionPolicy` to the module-level imports in `primitive_compiler.py` (needed for Task 6, correct to do it here):
```python
from agent_foundry.primitives.models import (
    ...
    RetryExceptionPolicy,   # add
    Retry,
    ...
)
```

**Verify:**
- `pdm test-unit tests/agent_foundry/compiler/test_ai_call_executor.py` — all green
- `pdm test-unit tests/agent_foundry/compiler/test_ai_call_compiler.py` — still green (B1)

---

## Task 5.5 — Eval path: respect AICall.executor (AC B6)

**Scope:** Update `build_invoke_ai_call_task` in `evals/agent_foundry_tasks.py` to branch on `call.executor` rather than always calling `invoke_ai_call` directly.

**Files touched:**
- `src/agent_foundry/evals/agent_foundry_tasks.py`
- `tests-evals/agent_foundry/evals/test_runner.py` (extend for B6)

**TDD steps:**

Extend `test_runner.py` with a `TestAICallExecutorInEvals` class covering AC B6:

```
B6. AICallRegistry with custom-executor AICall → eval invocation via build_invoke_ai_call_task
    runs the custom executor, not invoke_ai_call.
    Setup: register an AICall with a spy executor; build and run the eval task;
    assert the spy was called and invoke_ai_call was not called.
    (Use a mock/spy pattern on the executor field, not patching invoke_ai_call globally.)
```

Then update `build_invoke_ai_call_task`:

```python
def build_invoke_ai_call_task(call: AICall) -> Task:
    """Build a task that invokes ``call`` via its configured executor.

    When ``call.executor`` is None, falls back to ``invoke_ai_call``.
    When ``call.executor`` is set, the custom executor runs instead —
    consistent with how the compiler dispatches the same AICall.
    """
    import inspect as _inspect

    executor = call.executor
    executor_is_async = executor is not None and _inspect.iscoroutinefunction(executor)

    async def task(input_state: Any) -> BaseModel:
        if executor is None:
            from agent_foundry.ai_models.execute.invoke import invoke_ai_call
            return await invoke_ai_call(primitive=call, model_input=input_state)
        elif executor_is_async:
            return await executor(primitive=call, model_input=input_state)
        else:
            return executor(primitive=call, model_input=input_state)

    return task
```

**Verify:**
- `pdm test-unit tests-evals/agent_foundry/evals/test_runner.py` — all green including B6
- `pdm test-unit tests/agent_foundry/compiler/test_ai_call_executor.py` — still green

---

## Task 6 — `_compile_retry` exception policy (Capability A)

**Scope:** Implement snapshot/rollback, exception-to-failure conversion, lifecycle events, and `on_exhaustion` dispatch.

**Files touched:**
- `src/agent_foundry/compiler/primitive_compiler.py`
- `tests/agent_foundry/primitives/test_retry_exception_policy.py` (new)

**TDD steps:**

Write `test_retry_exception_policy.py` covering AC A1–A6:

```
A1. PROPAGATE (default) + body raises → exception propagates unchanged; workflow aborts.
    No new field needed to trigger this.

A2. TREAT_AS_FAILURE + max_attempts=3 + body raises on attempt 1 then succeeds on attempt 2
    with until() True → Retry exits successfully with body's attempt-2 output;
    attempt-1 exception is consumed.

A3. TREAT_AS_FAILURE + body raises every attempt + on_exhaustion set →
    on_exhaustion called with reason=BODY_EXCEPTIONS; its return value is the Retry output.

A4. TREAT_AS_FAILURE + body mutates state then raises → next attempt sees pre-mutation state
    (snapshot restored; no partial mutations carried forward).

A5. TREAT_AS_FAILURE + body raises → RETRY_ATTEMPT_FAILED lifecycle event captured per failure
    with attempt_num, exception_type, exception_message.

A6. All existing Retry tests pass unchanged (backward compat — run full compiler test suite).

on_exhaustion variants:
- on_exhaustion=None + TREAT_AS_FAILURE + all raises → silent exit with pre-Retry state
- on_exhaustion=None + CONDITION_NOT_MET → silent exit with last-attempt state (today's behaviour)
- on_exhaustion set (sync) + CONDITION_NOT_MET → hook called; reason=CONDITION_NOT_MET; return used
- on_exhaustion set (async) + TREAT_AS_FAILURE → hook awaited; reason=BODY_EXCEPTIONS; return used
- on_exhaustion set + mixed (some raised, some completed with until=False) → reason=MIXED
- on_exhaustion receives last_state equal to pre-Retry input when all attempts raised
```

Test helpers:
- `_raising_body(exc)` — `FunctionAction` whose function always raises the given exception
- `_succeed_on_attempt(n, output_fn)` — raises on attempts < n, then calls `output_fn` on attempt n
- `_mutating_then_raising_body(mutation_key, exc)` — mutates a state field then raises
- `_capturing_lifecycle_writer()` — collects appended events for assertion
- `_run_with_writer(plan, writer, initial_state)` — sets up `RunContext` with the capturing writer

Then update `_compile_retry` (note: `RetryExceptionPolicy` is now a top-level import per Task 5):

```python
def _compile_retry(
    graph: StateGraph,
    retry: Retry,
    ctx: CompileContext,
) -> CompileResult:
    import copy as _copy
    import inspect as _inspect
    from datetime import UTC, datetime

    retry_in, retry_out = get_type_args(retry)
    body_in, body_out = get_type_args(retry.body)

    # ... (body subgraph compilation unchanged) ...

    until_fn         = retry.until
    max_attempts     = retry.max_attempts
    exception_policy = retry.exception_policy
    on_exhaustion_fn = retry.on_exhaustion
    on_exhaustion_is_async = (
        on_exhaustion_fn is not None and _inspect.iscoroutinefunction(on_exhaustion_fn)
    )

    node_id = f"{ctx.prefix}_retry"

    async def retry_node(state: dict[str, Any]) -> dict[str, Any]:
        from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
        from agent_foundry.orchestration.run_context import current_run_context
        from agent_foundry.primitives.retry_types import (
            AttemptFailure,
            RetryExhaustion,
            RetryExhaustionReason,
        )

        ctx_opt = current_run_context.get()
        current_state = dict(state)
        attempt_failures: list[AttemptFailure] = []
        successful_completions = 0  # body ran to end; until() returned False

        for attempt_num in range(max_attempts):
            snapshot = _copy.deepcopy(current_state)
            try:
                result = await compiled_body.ainvoke(dict(current_state))
                current_state.update(_scope_out(result, body_out))
                model = _validate_scoped_input(current_state, retry_in, node_id)
                if until_fn(model):
                    return _scope_out(current_state, retry_out)
                successful_completions += 1
            except Exception as exc:
                if exception_policy == RetryExceptionPolicy.PROPAGATE:
                    raise
                # TREAT_AS_FAILURE: record, rollback, continue
                failure = AttemptFailure(
                    attempt_num=attempt_num + 1,
                    exception_type=type(exc).__name__,
                    exception_message=str(exc),
                    timestamp=datetime.now(UTC),
                )
                attempt_failures.append(failure)
                if ctx_opt is not None:
                    ctx_opt.lifecycle_writer.append(
                        LifecycleEvent.RETRY_ATTEMPT_FAILED,
                        node_id=node_id,
                        attempt_num=failure.attempt_num,
                        exception_type=failure.exception_type,
                        exception_message=failure.exception_message,
                    )
                current_state = snapshot  # discard partial mutations

        # --- Exhausted ---
        if on_exhaustion_fn is not None:
            if not attempt_failures:
                reason = RetryExhaustionReason.CONDITION_NOT_MET
            elif successful_completions == 0:
                reason = RetryExhaustionReason.BODY_EXCEPTIONS
            else:
                reason = RetryExhaustionReason.MIXED

            last_state_model = retry_in.model_validate(
                {k: current_state[k] for k in retry_in.model_fields if k in current_state}
            )
            exhaustion = RetryExhaustion(
                max_attempts=max_attempts,
                reason=reason,
                attempt_failures=attempt_failures,
                last_state=last_state_model,
            )
            if on_exhaustion_is_async:
                output = await on_exhaustion_fn(exhaustion)
            else:
                output = on_exhaustion_fn(exhaustion)
            if not isinstance(output, retry_out):
                raise PrimitiveCompilationError(
                    f"Retry {node_id}: on_exhaustion returned "
                    f"{type(output).__name__}, expected {retry_out.__name__}",
                    primitive_type=node_id,
                )
            return output.model_dump()

        # on_exhaustion is None: silent exit (today's behaviour for both exhaustion kinds)
        return _scope_out(current_state, retry_out)

    graph.add_node(node_id, retry_node)
    return CompileResult(node_id, node_id)
```

**Verify:**
- `pdm test-unit tests/agent_foundry/primitives/test_retry_exception_policy.py` — all green
- `pdm test-unit tests/agent_foundry/primitives/test_primitive_compiler.py` — existing Retry tests still green (AC A6)

---

## Task 7 — Interaction test (AC I1)

**Scope:** Verify the composed scenario. Body is `Sequence[ai_call_with_custom_executor, fallible_fn_action]` inside a `Retry` with `TREAT_AS_FAILURE`. Two sub-cases must hold together.

**Files touched:**
- `tests/agent_foundry/primitives/test_retry_aicall_interaction.py` (new)

**State model:**
```python
class ReviewState(BaseModel):
    verdict: str = "pending"
    attempt_count: int = 0
    fn_succeeded: bool = False
```

**Fixture setup:**

- `_raising_provider`: an `InferenceProvider` that always raises `ValueError("provider unavailable")`; used as the underlying provider for I1-a to ensure the catch branch in the custom executor is actually exercised
- `ai_call_with_catching_executor`: an `AICall` whose custom executor calls `_raising_provider` internally, catches `ValueError`, and returns `ReviewState(verdict="fallback_from_executor", ...)`. The executor is a real coroutine that exercises the try/except.
- `succeed_on_second_call`: a `FunctionAction` that raises `RuntimeError` on the first invocation and returns `ReviewState(verdict="ok", fn_succeeded=True)` on the second
- `body`: `Sequence[ai_call_with_catching_executor, succeed_on_second_call]`
- `retry`: `Retry[ReviewState, ReviewState](body=body, max_attempts=3, until=lambda s: s.verdict == "ok", exception_policy=TREAT_AS_FAILURE)`

**Test assertions for I1-a (AICall path — executor swallows exception internally):**
- The `_raising_provider` is called and raises `ValueError`
- The AICall's custom executor catches it and returns a synthesized `ReviewState`
- The `Retry` body's exception policy does **not** fire for this attempt; no `AttemptFailure` is recorded for the AICall step; `RETRY_ATTEMPT_FAILED` is **not** emitted for this case

**Test assertions for I1-b (FunctionAction path — exception propagates to Retry policy):**
- On the first attempt, `succeed_on_second_call` raises `RuntimeError`
- The Retry exception policy fires: `RETRY_ATTEMPT_FAILED` is emitted; state is rolled back
- On the second attempt, `succeed_on_second_call` succeeds; `verdict == "ok"`; workflow exits

**Composite assertion (I1-c):**
- The full workflow completes successfully with `verdict == "ok"`
- Exactly one `RETRY_ATTEMPT_FAILED` event is captured (from the `FunctionAction` raise, not from the AICall path)
- The AICall's custom executor spy records two calls (one per attempt where the Sequence reached it)

**Verify:**
- `pdm test-unit tests/agent_foundry/primitives/test_retry_aicall_interaction.py` — all green
- `pdm test-all` — full suite green

---

## Final verification

```
pdm test-all       # full suite including integration and evals
pdm typecheck      # Pyright — no new errors
pdm lint           # no new violations
pdm format         # no format changes
```

Confirm AC coverage:
- A1–A6: `test_retry_exception_policy.py`
- B1–B5: `test_ai_call_executor.py`
- B6: `test_runner.py` (Task 5.5)
- I1: `test_retry_aicall_interaction.py`
