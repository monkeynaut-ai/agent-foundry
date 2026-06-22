# Surface exec failures through the responder protocol

**Date:** 2026-05-16
**Status:** Design draft, not yet approved

## Goal

Treat agent exec failures (claude CLI exits non-zero, gives up after its
internal API retries, fails to produce a parseable envelope) as a
recoverable outcome routed through the existing `Responder` protocol —
the same seam that already handles `ClarificationOutcome` and
`PermissionOutcome`. This makes "agent is stuck, what do you want to do"
a uniform shape across the orchestration loop, gives interactive
responders a natural place to prompt the operator, and gives
programmatic responders a place to encode retry-vs-abort policy.

Motivated by run `2026-05-16-13-01-02`: claude exited with
`api_error_status: 500, num_turns: 2`. The orchestration layer
collapsed the failure into a fatal `AgentFailedError` and dropped the
entire run, even though a single retry would have likely succeeded.

## Scope

**In scope (v1):**

- New `ExecFailureOutcome` carrying structured cause fields
  (`exit_code`, `api_error_status`, `num_turns`, `error_summary`).
- Extend `Responder` protocol with an exec-failure handler returning
  one of `RETRY` or `ABORT`.
- Default base-class implementation returns `ABORT` so existing
  responders compile and preserve current behavior.
- `StdinResponder` prompts the operator: "exec failed (api 500, 2
  turns). retry / abort?"
- Inner turn loop in `container_executor`: when `AgentExecFailedError`
  is caught, build an `ExecFailureOutcome`, dispatch to the responder,
  on `RETRY` re-enter the turn with the same prompt; on `ABORT`
  propagate as today.

**Out of scope (v1, deferred):**

- Generic retry framework with configurable backoff. (Claude CLI
  already retries 5xx internally; the orchestration retry is one-shot
  fallback for the rare cases where claude's own retry budget is
  exhausted.)
- Routing OOM / SIGKILL through the responder. Those failures destroy
  the container, so retry without a fresh container is meaningless.
  Initially gate responder dispatch on
  `AgentExecFailedError.api_error_status is not None` (i.e. claude
  produced a `result` event before exiting) — that signals "claude
  itself gave up," which is recoverable.
- Multi-step retry policy (N retries with backoff). v1 is one-shot:
  responder says retry or abort; we honor it once.

## Background — what we have today

Source: `agent-foundry/src/agent_foundry/orchestration/container_executor.py`,
`agent-foundry/src/agent_foundry/agents/agent_turn_envelope.py`,
`agent-foundry/src/agent_foundry/responders/`.

Today's turn loop:
1. `await run_turn(...)` calls `_do_exec` which runs claude.
2. On success → envelope is parsed; outcome routed through existing
   dispatch (success / clarification / permission / failed).
3. On non-zero exit or no envelope → `AgentExecFailedError` raised.
4. Outer `except Exception` catches it, captures forensics, emits
   `AGENT_INVOCATION_FAILED`, re-raises as `AgentFailedError`.
5. Run dies.

The responder is wired into the success path (envelope-driven
outcomes). It never sees the exec-failure case.

## Design

### New outcome kind

```python
class ExecFailureOutcome(BaseModel):
    kind: Literal[TurnOutcomeKind.EXEC_FAILURE] = TurnOutcomeKind.EXEC_FAILURE
    exit_code: int
    api_error_status: int | None = None
    num_turns: int | None = None
    error_summary: str | None = None
```

Wrapped in the existing `AgentTurnEnvelope[O]` discriminated union the
same way `ClarificationOutcome` and `PermissionOutcome` are.

### Responder protocol extension

Add a typed request/response pair:

```python
class ExecFailureRequest(ResponderRequest):
    outcome_kind: Literal["exec_failure"] = "exec_failure"
    exit_code: int
    api_error_status: int | None
    num_turns: int | None
    error_summary: str | None

class ExecFailureAction(StrEnum):
    RETRY = "retry"
    ABORT = "abort"

class ExecFailureResponse(BaseModel):
    action: ExecFailureAction
```

Responder gains `handle_exec_failure(request, context) -> ExecFailureResponse`
on the base class, with a default returning `ABORT` (matches today's
behavior; existing responders that don't override compile and behave
unchanged).

### Inner turn loop change

In `container_executor._run`'s catch of `AgentExecFailedError`:

```python
except AgentExecFailedError as exec_err:
    # Only route through responder when claude itself gave up
    # (i.e. produced a structured result with api_error_status).
    if exec_err.api_error_status is not None and run_ctx.responder_provider:
        outcome = ExecFailureOutcome(
            exit_code=exec_err.exit_code,
            api_error_status=exec_err.api_error_status,
            num_turns=exec_err.num_turns,
            error_summary=exec_err.api_error_message,
        )
        action = await dispatch_to_responder(outcome, ...)
        if action is ExecFailureAction.RETRY:
            turn_number = live.next_turn()
            continue  # re-enter loop with same prompt
    # ABORT path (default) — existing behavior
    live.failed = True
    forensic_fields = _capture_forensic_fields(live, exit_code_hint=exec_err.exit_code)
    lifecycle.append(LifecycleEvent.AGENT_INVOCATION_FAILED, ..., **forensic_fields)
    raise AgentFailedError(...) from exec_err
```

Lifecycle events: emit `RESPONDER_REQUESTED` / `RESPONDER_ANSWERED`
around the dispatch (already used for clarification/permission, no new
event types needed).

### Migration / compat

- New protocol method has a default `ABORT` implementation on the
  Responder base class → existing Responder subclasses don't need
  changes to keep compiling. They opt in to handling exec failures by
  overriding.
- The new `ExecFailureOutcome` kind is in the discriminated union but
  is only constructed inside the executor on the failure path; no
  agent or product code emits it directly.
- Lifecycle event payload for `AGENT_INVOCATION_FAILED` on abort is
  unchanged.

## Tests (TDD)

1. `ExecFailureOutcome` round-trips through `AgentTurnEnvelope` JSON.
2. Default `Responder.handle_exec_failure` returns `ABORT`.
3. `StdinResponder.handle_exec_failure` prompts and parses
   `retry` / `abort`.
4. Inner loop catches `AgentExecFailedError` with `api_error_status`,
   builds `ExecFailureOutcome`, dispatches to responder. With a fake
   responder returning `RETRY`, the loop re-enters; with `ABORT`,
   `AgentFailedError` propagates.
5. Inner loop skips responder dispatch when
   `api_error_status is None` (OOM, SIGKILL, no-envelope) and falls
   straight to abort.
6. Lifecycle emits `RESPONDER_REQUESTED` / `RESPONDER_ANSWERED` around
   the dispatch.

## Open questions

1. **Default policy for non-interactive responders.** Should a
   programmatic `static_provider(SomeResponder())` default to `ABORT`
   (safe, current behavior) or `RETRY` (better DX, but masks failures)?
   Recommend `ABORT` — explicit opt-in to retry preserves blast-radius
   guarantees.
2. **Idempotency on retry.** Re-entering the turn with the same prompt
   re-uses the same session/container. Claude's `--resume` may or may
   not work cleanly here. Worth probing in implementation; if `--resume`
   fails on a half-completed retry, the right move is a fresh session
   (`current_resume = None`).
3. **Max retries.** v1 is one-shot. If the operator says RETRY and it
   fails again, the next failure aborts (responder protocol unchanged
   from there). Multi-retry policy is a follow-up.
