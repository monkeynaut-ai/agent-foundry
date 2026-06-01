# Plan: Clean run-termination signal for resolver ABORT (#70)

**Branch:** `markn/gh-70-resolver-abort-termination`
**Goal:** Make a resolver `ABORT` end a run as a deliberate, non-error terminal
outcome — distinguishable at the outcome layer from a genuine crash — without
forcing callers to pattern-match a raised exception. The runaway backstop
(`ResolverDidNotConvergeError`) stays an *error* terminal.

---

## Critical pre-condition — branch base (READ FIRST)

This worktree branch (`markn/gh-70-resolver-abort-termination`) was cut from an
**older `main`** that predates the operator-guided-retry resolver-seat work. The
machinery #70 builds on does **not exist on this branch**:

- `src/agent_foundry/primitives/retry_types.py` here still describes the removed
  `on_exhaustion` hook and `TREAT_AS_FAILURE` policy. It has **no**
  `DispositionKind`, `ResolverDisposition`, `RetryAborted`, or
  `ResolverDidNotConvergeError`.
- `src/agent_foundry/compiler/primitive_compiler.py` here has **no** resolver
  cycle (`_compile_retry` resolver/abort/re-entry nodes, `disposition_router`,
  `abort_node`).
- `src/agent_foundry/orchestration/lifecycle_events.py` here has **no**
  `RESOLVER_DISPOSITION`, `RETRY_ATTEMPT_PASSED/_NOT_PASSED/_ERRORED` members.

That work currently lives **only** on the unmerged branch
`feat/operator-guided-retry-resolver-seat` (commits `0a9bcf6`, `61b2e29`,
`3fa8fad`, etc.); it is **not** on `origin/main` (HEAD `6cee11d`, PR #58).

**Decision (assumption A1):** Task 0 below rebases this branch onto the resolver
work so #70 has a substrate to extend. Every file path and symbol in Tasks 1–6
refers to the **post-rebase** tree (i.e. the state of
`feat/operator-guided-retry-resolver-seat`), which is what the code excerpts in
this plan were read from. If the team would rather land the resolver branch to
`main` first and re-cut this branch, the Task 1–6 work is unchanged — only Task 0
differs. This is logged in Open Questions.

The single integration point that *is* identical on both bases is the runner's
terminal-event line:

```python
# src/agent_foundry/orchestration/runner.py:204
terminal = LifecycleEvent.RUN_FAILED if caught_exc is not None else LifecycleEvent.RUN_ENDED
```

That line is where the "operator abort looks like a crash" defect lives.

---

## Design decisions

**Mechanism (assumption A2): keep `RetryAborted` as the in-graph propagation
vehicle; classify it in the runner; swallow it into a clean terminal outcome.**

The issue lists four candidate mechanisms. Rationale for this one:

- The compiler already raises `RetryAborted` out of `abort_node`, and it
  propagates **raw** through `graph.ainvoke` (verified: `test_retry_resolver_e2e`
  catches it directly with `pytest.raises(RetryAborted, ...)`). A sentinel return
  value or a LangGraph-level signal would require reworking the compiled graph's
  exit semantics and the resolver cycle — more platform churn for no added
  product capability. Per the platform's "push complexity into the platform, not
  onto products" rule, the smallest change that gives products a clean,
  non-error terminal outcome wins.
- The runner already has the exact seam: a single `finally` block with
  `caught_exc` in scope that decides the terminal event. Classifying there is
  local and testable.

So: the runner catches `RetryAborted` **separately**, records it as a deliberate
abort (new `RUN_ABORTED` terminal event + reason carried on `RunEndedEvent`),
and **does not re-raise** it — `run_primitive_plan` returns normally. All other
exceptions (including `ResolverDidNotConvergeError`) keep the existing
re-raise + `RUN_FAILED` path.

**Terminal lifecycle taxonomy (assumption A3):** add one new wire-stable event,
`RUN_ABORTED = "run_aborted"`, to `LifecycleEvent`. The issue asks the terminal
event to distinguish "completed / operator-aborted / safety-backstop-tripped /
crashed". Mapping:

| Outcome | Caught exception | Terminal event |
|---|---|---|
| clean success | `None` | `RUN_ENDED` |
| operator abort | `RetryAborted` | `RUN_ABORTED` |
| safety backstop | `ResolverDidNotConvergeError` | `RUN_FAILED` |
| crash | any other | `RUN_FAILED` |

The backstop and a crash both map to `RUN_FAILED`; they remain distinguishable
by the exception payload on `RunEndedEvent` and (already today) by the absence of
a `RESOLVER_DISPOSITION(kind="abort")` record. Adding a *separate*
`RUN_BACKSTOP_TRIPPED` event is **not** in this plan — the issue explicitly wants
the backstop to "remain an *error* terminal", and a distinct error event is a
nice-to-have not required by the desired behavior. Logged in Open Questions.

**Return value of `run_primitive_plan` on abort (assumption A4):** on
`RetryAborted` the graph never produced a validated `root_out`, so there is no
`final_output` to return. `run_primitive_plan` is annotated `-> BaseModel`.
Rather than widen the signature to `BaseModel | None` (ripples to every caller)
or invent a synthetic output model (a product decision the platform must not
make), the runner **re-raises is avoided but the function still cannot fabricate
output**. Chosen: introduce a typed terminal-outcome carrier.

`run_primitive_plan` keeps returning `BaseModel` on success. On abort it returns
the **pre-abort accumulated state coerced to `root_out` is not available**, so
instead the abort path returns a new lightweight typed model
`RunAbortedOutcome(reason: str)` — and the signature widens to
`BaseModel` (unchanged) because `RunAbortedOutcome` *is* a `BaseModel`. Callers
that want to distinguish abort from success check
`isinstance(result, RunAbortedOutcome)` **or** read the new field on
`RunEndedEvent` (preferred). The abort reason is thereby available without
catching a raised exception — satisfying the issue's third bullet. `RetryAborted`
remains importable for any caller that still wants the type. Logged in Open
Questions as the main reviewable design choice.

**`RunEndedEvent` carries the reason (assumption A5):** add
`aborted: bool = False` and `abort_reason: str | None = None` to
`RunEndedEvent`. Today the event encodes terminal state as the (exception,
output) pair; the docstring table is extended with the abort row. This is the
hook-facing channel for the abort reason and is forward-compatible (new fields,
existing hooks unaffected).

**Summary classification (assumption A6):** `render_summary` currently derives
`status` from `RUN_FAILED` presence (`"failed"` vs `"completed"`). Extend it to a
three-way classification (`completed` / `aborted` / `failed`) keyed off the new
`RUN_ABORTED` event, and surface the abort reason line. This satisfies #69's
dependency on #70 (summary reports the terminal *outcome*).

**Interaction with #66 (GateAction interrupt/resume):** out of scope here. #66
touches resume semantics; #70 only touches terminal classification. No shared
edit in this plan. Noted in Open Questions for the reviewer to confirm no merge
collision on `runner.py`.

---

## Task 0 — Establish the resolver substrate (rebase)

**Goal:** Make the resolver/ABORT machinery present on this branch so Tasks 1–6
have something to extend.

### 0a. Rebase

```
git rebase feat/operator-guided-retry-resolver-seat
```

(Equivalently, once that branch merges, rebase onto `origin/main`.)

### 0b. Verify substrate present and green

```
pdm run test-unit -- tests/agent_foundry/primitives/test_retry_resolver.py tests/agent_foundry/primitives/test_retry_resolver_e2e.py -q
pdm run typecheck
```

Both must pass before proceeding. Confirm these symbols now resolve:
`RetryAborted`, `ResolverDidNotConvergeError`, `DispositionKind`,
`ResolverDisposition` in `src/agent_foundry/primitives/retry_types.py`, and
`LifecycleEvent.RESOLVER_DISPOSITION`.

> If the rebase is declined for process reasons, STOP and escalate — Tasks 1–6
> cannot be implemented against the current (pre-resolver) base.

---

## Task 1 — Add `RUN_ABORTED` lifecycle event

**File:** `src/agent_foundry/orchestration/lifecycle_events.py`

### 1a. Write failing test (RED)

**File:** `tests/agent_foundry/orchestration/test_lifecycle_events.py`

Add a test asserting the new member exists with its wire value:

```python
def test_run_aborted_event_value():
    assert LifecycleEvent.RUN_ABORTED.value == "run_aborted"
```

### 1b. Implement (GREEN)

Add after `RUN_FAILED` in `LifecycleEvent`:

```python
    RUN_ABORTED = "run_aborted"
```

(Wire-stable string per the module docstring's "treat the string as a wire
format" rule.)

### 1c. Verify

```
pdm run test-unit -- tests/agent_foundry/orchestration/test_lifecycle_events.py -q
```

---

## Task 2 — Add `RunAbortedOutcome` typed terminal model

**File:** `src/agent_foundry/primitives/retry_types.py`

### 2a. Write failing test (RED)

**File:** `tests/agent_foundry/primitives/test_retry_types.py`

```python
def test_run_aborted_outcome_carries_reason():
    outcome = RunAbortedOutcome(reason="operator-declined")
    assert outcome.reason == "operator-declined"
    # round-trips as a pydantic model
    assert RunAbortedOutcome.model_validate(outcome.model_dump()).reason == "operator-declined"
```

### 2b. Implement (GREEN)

Add to `retry_types.py`:

```python
class RunAbortedOutcome(BaseModel):
    """Terminal outcome returned by ``run_primitive_plan`` when a resolver ABORT
    ended the run deliberately. ``reason`` is the operator's ABORT explanation."""

    reason: str = ""
```

> Placement assumption (A7): co-located with `RetryAborted` / `ResolverDisposition`
> because it is the non-exception twin of the abort reason already carried by
> `RetryAborted`. An alternative home is `run_context.py` next to `RunEndedEvent`;
> chose `retry_types.py` to keep all resolver-abort vocabulary in one module.

### 2c. Verify

```
pdm run test-unit -- tests/agent_foundry/primitives/test_retry_types.py -q
pdm run typecheck
```

---

## Task 3 — Carry abort reason on `RunEndedEvent`

**File:** `src/agent_foundry/orchestration/run_context.py`

### 3a. Write failing test (RED)

**File:** `tests/agent_foundry/orchestration/test_run_context.py` (or
`test_run_context_hooks.py` — match where `RunEndedEvent` is already exercised)

```python
def test_run_ended_event_defaults_not_aborted(run_context):
    ev = RunEndedEvent(run_context=run_context)
    assert ev.aborted is False
    assert ev.abort_reason is None

def test_run_ended_event_can_record_abort(run_context):
    ev = RunEndedEvent(run_context=run_context, aborted=True, abort_reason="declined")
    assert ev.aborted is True
    assert ev.abort_reason == "declined"
```

### 3b. Implement (GREEN)

Add the two fields to `RunEndedEvent` (after `output`):

```python
    aborted: bool = False
    abort_reason: str | None = None
```

Extend the class docstring's terminal-state table with the abort row
(exception=`None`, output=a `RunAbortedOutcome`, aborted=`True`).

### 3c. Verify

```
pdm run test-unit -- tests/agent_foundry/orchestration/test_run_context.py tests/agent_foundry/orchestration/test_run_context_hooks.py -q
pdm run typecheck
```

---

## Task 4 — Classify `RetryAborted` in the runner (core change)

**File:** `src/agent_foundry/orchestration/runner.py`

This is the defect site. Today (line ~196 and ~204):

```python
    except BaseException as exc:
        caught_exc = exc
        raise
    finally:
        ...
        terminal = LifecycleEvent.RUN_FAILED if caught_exc is not None else LifecycleEvent.RUN_ENDED
        lifecycle.append(terminal, run_id=resolved_run_id)
```

### 4a. Write failing tests (RED)

**File:** `tests/agent_foundry/compiler/test_run_primitive_plan.py`
(this is where the terminal-event behavior is already tested —
`test_exception_mid_run_propagates_and_cleans_up`, `test_happy_path...`).

Add three tests using a plan whose root is a `Retry` with an ABORT resolver
(reuse the `W` / `_designer_body` / ABORT `FunctionAction` fixtures from
`tests/agent_foundry/primitives/test_retry_resolver_e2e.py` — lift the minimal
fixture into the test or import it):

```python
async def test_resolver_abort_terminates_clean_not_failed(tmp_path, ...):
    """ABORT -> run_primitive_plan returns RunAbortedOutcome (does NOT raise);
    lifecycle terminal event is RUN_ABORTED, not RUN_FAILED."""
    result = await run_primitive_plan(_plan_with_abort_resolver("cannot-converge"), ...)
    assert isinstance(result, RunAbortedOutcome)
    assert result.reason == "cannot-converge"
    types = [json.loads(l)["type"] for l in (run_dir / "lifecycle.jsonl").read_text().splitlines()]
    assert LifecycleEvent.RUN_ABORTED.value in types
    assert LifecycleEvent.RUN_FAILED.value not in types

async def test_resolver_abort_on_run_ended_hook_sees_reason(tmp_path, ...):
    """on_run_ended hook receives aborted=True and the reason; exception is None."""
    captured = []
    await run_primitive_plan(..., on_run_ended=[lambda e: captured.append(e)])
    (ev,) = captured
    assert ev.aborted is True
    assert ev.abort_reason == "cannot-converge"
    assert ev.exception is None

async def test_backstop_did_not_converge_is_still_run_failed(tmp_path, ...):
    """ResolverDidNotConvergeError keeps the error terminal: it propagates AND
    the terminal event is RUN_FAILED (not RUN_ABORTED)."""
    with pytest.raises(ResolverDidNotConvergeError):
        await run_primitive_plan(_plan_that_never_converges(), ...)
    types = [...]
    assert LifecycleEvent.RUN_FAILED.value in types
    assert LifecycleEvent.RUN_ABORTED.value not in types
```

> Fixture assumption (A8): `_plan_that_never_converges()` is a `Retry` whose
> resolver always returns RETRY and whose body never passes `until`, with
> `resolver_max_reentries` small, so the backstop trips. Confirm the field name
> `resolver_max_reentries` against the rebased `Retry` model when writing.

### 4b. Implement (GREEN)

Replace the single-catch with abort-aware classification. Capture the abort
separately so it is **not** re-raised and the terminal event differs:

```python
    caught_exc: BaseException | None = None
    abort_reason: str | None = None
    final_output: BaseModel | None = None
    try:
        graph = compile_runtime_plan(plan)
        result_dict = await graph.ainvoke(initial_state.model_dump())
        final_output = root_out.model_validate(result_dict)
        return final_output
    except RetryAborted as aborted:
        # Deliberate operator abort: a clean, non-error terminal outcome.
        abort_reason = aborted.reason
        final_output = RunAbortedOutcome(reason=aborted.reason)
        return final_output
    except BaseException as exc:
        caught_exc = exc
        raise
    finally:
        if abort_reason is not None:
            terminal = LifecycleEvent.RUN_ABORTED
        elif caught_exc is not None:
            terminal = LifecycleEvent.RUN_FAILED
        else:
            terminal = LifecycleEvent.RUN_ENDED
        lifecycle.append(terminal, run_id=resolved_run_id)
        ...
        _safe_invoke_hooks(
            run_ctx.on_run_ended,
            RunEndedEvent(
                run_context=run_ctx,
                exception=caught_exc,
                output=final_output,
                aborted=abort_reason is not None,
                abort_reason=abort_reason,
            ),
            label="on_run_ended",
        )
```

Add imports: `RetryAborted`, `RunAbortedOutcome` from
`agent_foundry.primitives.retry_types`.

Update the `run_primitive_plan` docstring teardown paragraph (lines ~101–108) to
describe the three-way terminal classification and that `RetryAborted` is caught
(not propagated) and surfaced as `RunAbortedOutcome` + `RunEndedEvent.aborted`.

> Ordering note (load-bearing): the `except RetryAborted` clause must precede the
> broad `except BaseException` clause, else the abort is swallowed by the generic
> handler and re-raised as a failure.

### 4c. Verify

```
pdm run test-unit -- tests/agent_foundry/compiler/test_run_primitive_plan.py -q
pdm run typecheck
```

---

## Task 5 — Classify outcome in `render_summary`

**File:** `src/agent_foundry/orchestration/summary.py`

### 5a. Write failing test (RED)

**File:** `tests/agent_foundry/orchestration/test_summary.py`

```python
def test_summary_reports_aborted_outcome(tmp_path):
    """A lifecycle stream ending in RUN_ABORTED renders status 'aborted'
    (not 'failed', not 'completed')."""
    # write a minimal jsonl: RUN_STARTED ... RESOLVER_DISPOSITION(kind=abort) ... RUN_ABORTED
    ...
    render_summary(run_dir)
    text = (run_dir / "summary.txt").read_text()
    assert "aborted" in text
    assert "failed" not in text
```

(Mirror the existing `test_summary.py` jsonl-fixture style.)

### 5b. Implement (GREEN)

In `render_summary`:

- Add a `run_aborted = False` accumulator alongside `run_failed`.
- Add a branch handling `LifecycleEvent.RUN_ABORTED.value`: set
  `run_ended_at = ts` and `run_aborted = True`.
- Replace the two-way `status = "failed" if run_failed else "completed"` with a
  three-way: `"aborted"` if `run_aborted`, else `"failed"` if `run_failed`, else
  `"completed"`.
- Surface the abort reason when present: read it from the
  `RESOLVER_DISPOSITION` record whose `kind == "abort"` (the
  `reason` field is already emitted there by the compiler's
  `disposition_router`). Append an `Abort reason: <reason>` line near the header.

> Assumption (A9): the summary reads the abort reason from the existing
> `RESOLVER_DISPOSITION(kind="abort", reason=...)` record rather than adding a
> `reason` field to the `RUN_ABORTED` event. Keeps `RUN_ABORTED` a pure terminal
> marker and avoids duplicating the reason on the wire. If the reviewer prefers
> the reason on `RUN_ABORTED` itself, that's a one-line change in Task 4's
> `lifecycle.append(terminal, ...)` plus this reader. Logged in Open Questions.

### 5c. Verify

```
pdm run test-unit -- tests/agent_foundry/orchestration/test_summary.py -q
```

---

## Task 6 — Refresh docstrings and full-suite regression

### 6a. Docstring corrections (REFACTOR)

- `RetryAborted` docstring in `retry_types.py` currently says *"Terminates the
  run via the raise path (clean-signal variant deferred)."* — update to state the
  runner now classifies it into a clean `RUN_ABORTED` terminal and surfaces
  `RunAbortedOutcome` / `RunEndedEvent.aborted`. (Per the comment-discipline
  rule, keep it about *this* type's contract; do not restate the runner's
  internals beyond the load-bearing fact that the raise is caught, not fatal.)
- Confirm the `run_primitive_plan` docstring edit from Task 4b reads correctly.

### 6b. Full unit + typecheck regression

```
pdm run test-unit
pdm run typecheck
```

All unit tests green and zero pyright errors before the plan is complete. Pay
attention to the resolver e2e tests from Task 0 — `RetryAborted` still raises
*inside the graph* (those tests use `_compile_and_run`, not
`run_primitive_plan`, so they still expect the raise and must stay green
unchanged).

---

## Completion criteria

- [ ] Branch rebased onto resolver substrate; resolver tests green (Task 0).
- [ ] `LifecycleEvent.RUN_ABORTED` exists (`"run_aborted"`).
- [ ] `RunAbortedOutcome(reason)` pydantic model exists and round-trips.
- [ ] `RunEndedEvent` carries `aborted` + `abort_reason`.
- [ ] `run_primitive_plan` returns `RunAbortedOutcome` on ABORT, does **not**
      raise, and writes `RUN_ABORTED` (not `RUN_FAILED`).
- [ ] `ResolverDidNotConvergeError` still propagates and writes `RUN_FAILED`.
- [ ] `render_summary` reports `aborted` vs `failed` vs `completed` and shows the
      abort reason.
- [ ] `RetryAborted` remains importable; in-graph resolver e2e tests unchanged.
- [ ] `pdm run test-unit` and `pdm run typecheck` both clean.

---

## Open Questions / Decisions for Review

1. **(A1) Branch base / rebase.** This branch lacks the resolver/ABORT
   machinery #70 extends; that code is only on the unmerged
   `feat/operator-guided-retry-resolver-seat` branch (not on `origin/main`,
   HEAD #58). Task 0 rebases onto it. **Decision needed:** rebase onto the
   resolver branch now, or wait for it to merge to `main` and re-cut? Tasks 1–6
   are identical either way.

2. **(A2) Mechanism.** Chosen: keep `RetryAborted` raising out of the graph,
   catch+classify+swallow in the runner. The issue listed alternatives (sentinel
   return, typed terminal-outcome from the graph, LangGraph-level signal). I
   picked the lowest-churn option that still removes the caller's need to
   type-match. Confirm this is the intended mechanism.

3. **(A4) `run_primitive_plan` return type on abort.** On ABORT there is no
   validated `root_out`. Chosen: return a new `RunAbortedOutcome(reason=...)`
   (a `BaseModel`, so the `-> BaseModel` signature is unchanged) instead of
   widening to `BaseModel | None` or fabricating a product output model. Callers
   distinguish via `isinstance(result, RunAbortedOutcome)` or, preferred, the new
   `RunEndedEvent.aborted` field. **This is the main reviewable design choice.**
   Alternative: keep returning the pre-abort accumulated state coerced to
   `root_out` — rejected because that state never passed `until` and coercing it
   would be a misleading "success-shaped" return.

4. **(A3) Backstop terminal event.** `ResolverDidNotConvergeError` maps to
   `RUN_FAILED` (stays an error), distinguishable from a crash only by the
   exception payload, not a dedicated event. Should the backstop get its own
   `RUN_BACKSTOP_TRIPPED` wire event? The issue only requires it "remain an error
   terminal", so I did not add one. Confirm.

5. **(A9) Where the abort reason lives on the wire.** The summary reads the
   reason from the existing `RESOLVER_DISPOSITION(kind="abort")` record rather
   than duplicating it onto the `RUN_ABORTED` event. If you prefer the reason on
   the terminal event itself, it's a one-line change in Task 4 + Task 5. Confirm.

6. **(#66 interaction)** #66 (GateAction interrupt/resume) also touches
   run-termination/outcome semantics and `runner.py`. This plan's only
   `runner.py` edit is the terminal-classification block (lines ~196–229).
   Reviewer should confirm no collision with in-flight #66 work on the same
   block; if #66 lands first, re-check the `except`-clause ordering survives.

7. **(#62 overlap — primitive_compiler.py)** #62 ("centralize `child_specs`")
   refactors `primitive_compiler.py`: `_collect_retry_channels` (~164–197) and
   each `_compile_*` / validator child-enumeration. **This plan touches
   `primitive_compiler.py` essentially not at all** — #70's compiler dependency
   (`abort_node` raising `RetryAborted`, `disposition_router`) is *consumed
   unchanged*; #70 adds no edits there. Overlap risk between #70 and #62 on
   `primitive_compiler.py` is therefore **low/none**: #62 reshapes
   child-enumeration plumbing; #70 only adds runner/lifecycle/summary/types code.
   The one shared *file* they both depend on (read-only for #70) is
   `primitive_compiler.py`, but they edit disjoint regions. Sequencing is free in
   either order; flagged so a reviewer can confirm no line-level merge conflict if
   both land close together.
