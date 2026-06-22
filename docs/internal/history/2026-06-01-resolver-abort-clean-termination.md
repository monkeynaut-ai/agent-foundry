# Plan: Unified typed terminal-outcome envelope (`RunOutcome`) for #70

**Branch:** `markn/gh-70-resolver-abort-termination`
**Goal:** Replace the runner's untyped terminal seam (return `BaseModel` on
success, re-raise on failure, no abort concept) with a single **typed
terminal-outcome envelope**, `RunOutcome`. Every run ends by returning exactly
one `RunOutcome` variant:

- **completed** — the validated product output,
- **aborted** — a deliberate operator ABORT (NOT an error),
- **failed** — a safety backstop trip or an unexpected crash, distinguished by a
  typed `error_kind`.

A resolver `ABORT` becomes a first-class, non-error terminal outcome that callers
read off the envelope — never by pattern-matching a raised exception. The runaway
backstop (`ResolverDidNotConvergeError`) and any other crash become
`RunFailed`, distinguished by `error_kind`, not by which exception escaped.

---

## Substrate is already present (READ FIRST — supersedes the old rebase plan)

The previous revision of this plan opened with a "Task 0 rebase" because it was
written against an older base that lacked the resolver/ABORT machinery. **That is
no longer true on this branch.** Verified by reading the live tree:

- `src/agent_foundry/primitives/retry_types.py` already defines `DispositionKind`,
  `ResolverDisposition`, `RetryAborted`, and `ResolverDidNotConvergeError`.
- `src/agent_foundry/orchestration/lifecycle_events.py` already defines
  `RESOLVER_DISPOSITION`, `RETRY_ATTEMPT_PASSED`, `RETRY_ATTEMPT_NOT_PASSED`,
  `RETRY_ATTEMPT_ERRORED`.
- The compiler already raises `RetryAborted` out of `abort_node` and
  `ResolverDidNotConvergeError` at the backstop ceiling.

**There is no rebase task.** Tasks below extend the live tree directly.

The runner's terminal seam today
(`src/agent_foundry/orchestration/runner.py` ~lines 189–229):

```python
caught_exc: BaseException | None = None
final_output: BaseModel | None = None
try:
    graph = compile_runtime_plan(plan)
    result_dict = await graph.ainvoke(initial_state.model_dump())
    final_output = root_out.model_validate(result_dict)
    return final_output
except BaseException as exc:
    caught_exc = exc
    raise
finally:
    terminal = LifecycleEvent.RUN_FAILED if caught_exc is not None else LifecycleEvent.RUN_ENDED
    lifecycle.append(terminal, run_id=resolved_run_id)
    ...
    RunEndedEvent(run_context=run_ctx, exception=caught_exc, output=final_output)
```

This is the single seam we replace. Return type is currently `-> BaseModel`.

---

## Design decisions

### D1 — `RunOutcome` discriminated union (the envelope)

A tagged discriminated union, per the repo's data-model conventions (StrEnum
discriminator, tagged wrappers, `Annotated[Union[...], Field(discriminator=...)]`,
no `Literal` for the routing value).

```python
class RunOutcomeKind(StrEnum):
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"


class FailureKind(StrEnum):
    BACKSTOP = "backstop"   # ResolverDidNotConvergeError — safety invariant trip
    CRASH = "crash"         # any other escaped exception


class RunCompleted(BaseModel):
    kind: RunOutcomeKind = RunOutcomeKind.COMPLETED
    output: BaseModel       # the validated product output (root_out instance)


class RunAborted(BaseModel):
    kind: RunOutcomeKind = RunOutcomeKind.ABORTED
    reason: str = ""        # operator's ABORT explanation


class RunFailed(BaseModel):
    kind: RunOutcomeKind = RunOutcomeKind.FAILED
    error_kind: FailureKind
    error_type: str         # exception class __name__, for reporting
    message: str            # str(exc)


RunOutcome = Annotated[
    Union[RunCompleted, RunAborted, RunFailed],
    Field(discriminator="kind"),
]
```

> **Discriminator-typing note (assumption D1a):** the convention prefers
> `kind: RunOutcomeKind = RunOutcomeKind.VARIANT`. If the pinned Pydantic version
> rejects a `StrEnum`-typed discriminator on a tagged union, fall back to the
> sanctioned form `kind: Literal[RunOutcomeKind.VARIANT] = RunOutcomeKind.VARIANT`
> on each wrapper. Decide at GREEN by running `pdm run typecheck` + a round-trip
> test; pick whichever the version accepts. Logged in Open Questions.

> **`RunCompleted.output` typing (assumption D1b):** typed `BaseModel` (not
> generic). `run_primitive_plan` is itself non-generic (`root_out` is resolved at
> runtime via `get_type_args`), so a parameterized `RunCompleted[O]` would not buy
> static typing at the call site. Callers narrow with `isinstance(result.output, ...)`
> exactly as they do today against the bare return. Logged in Open Questions.

> **`RunFailed` payload (assumption D1c):** carries `error_kind` + `error_type` +
> `message` (string-reconstructable report) rather than the live `BaseException`
> object. Rationale: `RunOutcome` is a Pydantic model intended to round-trip;
> embedding a live exception forces `arbitrary_types_allowed` and breaks JSON
> serialization. The live exception is still delivered to `on_run_ended` hooks via
> `RunEndedEvent.exception` (unchanged), so nothing loses the traceback-bearing
> object. Logged in Open Questions.

### D2 — Module placement: `orchestration/run_outcome.py` (CRITICAL)

`RunOutcome`, `RunOutcomeKind`, `FailureKind`, and the three wrappers live in a
**new module `src/agent_foundry/orchestration/run_outcome.py`** — NOT in
`src/agent_foundry/primitives/retry_types.py`.

**Why this matters (issue-disjointness constraint):** issue #62 ("centralize
`child_specs`") is actively reshaping `primitives/` and
`compiler/primitive_compiler.py`. Putting the terminal-outcome vocabulary in
`primitives/retry_types.py` would couple #70's edits to #62's churn and create
avoidable merge conflicts. The terminal envelope is an **orchestration** concept
(it is what the runner returns), so it belongs in `orchestration/`. This keeps
#70's writable surface entirely inside `orchestration/` (+ its tests), disjoint
from #62. `retry_types.py` is consumed **read-only** by #70 (the runner imports
`RetryAborted` and `ResolverDidNotConvergeError` for `except` clauses; it adds
nothing there).

### D3 — Mechanism: `RetryAborted` stays an internal unwind signal; the runner is the single typed boundary

Keep `RetryAborted` raising out of `abort_node` and propagating raw through
`graph.ainvoke` (unchanged — the in-graph resolver e2e tests still
`pytest.raises(RetryAborted)`). The runner's except/finally seam is the **single
place** that converts the four terminal conditions into one `RunOutcome` variant:

| Terminal condition                | Caught in runner                | `RunOutcome` returned                 |
|-----------------------------------|---------------------------------|---------------------------------------|
| graph returns, output validates   | (none)                          | `RunCompleted(output=…)`              |
| operator abort                    | `RetryAborted`                  | `RunAborted(reason=…)`                |
| safety backstop                   | `ResolverDidNotConvergeError`   | `RunFailed(error_kind=BACKSTOP, …)`   |
| any other crash                   | `BaseException`                 | `RunFailed(error_kind=CRASH, …)`      |

`RetryAborted` and `ResolverDidNotConvergeError` are **internal unwind signals**
that never escape `run_primitive_plan`. After this change the function does not
re-raise — every path returns a `RunOutcome`. (See D6 for the re-raise
behavior-change and its test blast radius.)

> **Not through the compiler (DEFERRED to #66):** the approved design explicitly
> keeps the typed boundary in the *runner*, not a compiled terminal node. Routing
> a typed terminal node through the compiler is **out of scope for #70** and
> deferred to issue #66 (GateAction interrupt/resume, which reworks compiled-graph
> exit semantics). Stated here so #70 does not collide with #62's
> `primitive_compiler.py` work or over-build. `runner.py` is the only behavioral
> edit; the compiler is untouched.

### D4 — Lifecycle taxonomy: add `RUN_ABORTED`

Add one wire-stable event `RUN_ABORTED = "run_aborted"`. Terminal mapping:

| `RunOutcome`                       | Terminal lifecycle event |
|------------------------------------|--------------------------|
| `RunCompleted`                     | `RUN_ENDED`              |
| `RunAborted`                       | `RUN_ABORTED`            |
| `RunFailed(BACKSTOP)`              | `RUN_FAILED`             |
| `RunFailed(CRASH)`                 | `RUN_FAILED`             |

The backstop/crash distinction is carried by the typed `RunFailed.error_kind`
field, **not** a separate wire event. No `RUN_BACKSTOP_TRIPPED` event is added —
the typed field is the source of truth and a distinct wire event would duplicate
it. Logged in Open Questions.

### D5 — `RunEndedEvent` carries the typed outcome

Add `outcome: RunOutcome | None = None` to `RunEndedEvent`. The hook now reads the
terminal classification (completed / aborted / failed+error_kind + abort reason)
off one typed field.

**Back-compat for `exception` / `output`:** keep both existing fields.

- `output`: set to the product `BaseModel` on completion; `None` otherwise
  (unchanged contract for existing success/failure hooks).
- `exception`: set to the live `BaseException` on a CRASH/BACKSTOP failure; `None`
  on completion **and on abort** (abort is not an error). This preserves every
  existing hook that reads `event.exception` / `event.output`, while
  `event.outcome` is the new richer channel. The docstring's two-row terminal
  table grows to four rows (completed / aborted / backstop / crash).

> **Assumption D5a:** on `RunAborted`, `output` is `None` and `exception` is
> `None`; the abort is legible only via `event.outcome` (a `RunAborted`). This is
> the one case where the legacy (exception, output) pair `(None, None)` is
> ambiguous with "never ran" — but a hook only ever fires post-run, so `(None,
> None)` + `outcome=RunAborted` is unambiguous. Logged in Open Questions.

### D6 — `run_primitive_plan` no longer re-raises (behavior change)

Today the runner **re-raises** on any exception. Under the envelope it **returns
`RunFailed`** instead. This is the deliberate point of the unified envelope:
callers branch on `RunOutcome.kind`, never on `try/except`.

This changes the contract for the FAILED path and touches every test that asserts
the runner propagates an exception. Enumerated in the blast radius (Task 6) and
flagged as the primary reviewable decision in Open Questions (D6 alternative:
keep re-raising CRASH/BACKSTOP and only return for COMPLETED/ABORTED — rejected
because it leaves callers pattern-matching exceptions for failures, defeating the
"single typed terminal envelope" goal).

### D7 — `render_summary`: three-way classification

`render_summary` currently derives `status` as `"failed" if run_failed else
"completed"`. Extend to three-way `completed` / `aborted` / `failed`, keyed off
`RUN_ABORTED` / `RUN_FAILED` presence, and surface:

- the **abort reason** (read from the existing
  `RESOLVER_DISPOSITION(kind="abort", reason=…)` record — already emitted by the
  compiler), and
- the **failure `error_kind`** when failed.

Where does `error_kind` come from in the jsonl? Two options (assumption D7a):
(a) read it off an enriched `RUN_FAILED` record if Task 4 writes `error_kind`
into the terminal event payload; (b) infer backstop by the presence of a
`ResolverDidNotConvergeError`-shaped record. **Chosen: (a)** — Task 4 attaches
`error_kind` to the `RUN_FAILED` lifecycle record so the summary reads one field
instead of inferring. Logged in Open Questions. This labeled terminal outcome
also satisfies issue **#69**'s dependency on a classified terminal result.

### D8 — Interaction with #62 / #66

- **#62** reshapes `primitives/` + `primitive_compiler.py` child-enumeration.
  #70 edits none of that (D2 keeps the envelope in `orchestration/`; the compiler
  is read-only for #70). No line-level overlap expected.
- **#66** reworks compiled-graph exit/resume semantics. #70's typed-terminal-node-
  in-compiler is explicitly deferred to #66 (D3). #70's only `runner.py` edit is
  the terminal-classification block; reviewer should confirm no collision if #66
  lands first.

---

## Task 1 — `RunOutcome` envelope module

**New file:** `src/agent_foundry/orchestration/run_outcome.py`
**New test:** `tests/agent_foundry/orchestration/test_run_outcome.py`

### 1a. RED

```python
def test_run_completed_round_trips():
    out = RunCompleted(output=_SomeModel(x=1))
    assert out.kind is RunOutcomeKind.COMPLETED

def test_run_aborted_carries_reason():
    out = RunAborted(reason="cannot-converge")
    assert out.kind is RunOutcomeKind.ABORTED
    assert out.reason == "cannot-converge"

def test_run_failed_carries_error_kind():
    out = RunFailed(error_kind=FailureKind.BACKSTOP, error_type="ResolverDidNotConvergeError", message="…")
    assert out.kind is RunOutcomeKind.FAILED
    assert out.error_kind is FailureKind.BACKSTOP

def test_discriminated_union_dispatches_on_kind():
    # validate a RunOutcome-typed adapter routes by kind
    from pydantic import TypeAdapter
    ta = TypeAdapter(RunOutcome)
    got = ta.validate_python({"kind": "aborted", "reason": "r"})
    assert isinstance(got, RunAborted)
```

### 1b. GREEN

Implement `RunOutcomeKind`, `FailureKind`, the three wrappers, and the
`RunOutcome` alias exactly as in D1. Resolve the discriminator-typing fork (D1a)
to whatever pyright + Pydantic accept. Add `__all__`.

### 1c. Verify

```
pdm run test-unit -- tests/agent_foundry/orchestration/test_run_outcome.py -q
pdm run typecheck
```

---

## Task 2 — `RUN_ABORTED` lifecycle event

**File:** `src/agent_foundry/orchestration/lifecycle_events.py`
**Test:** `tests/agent_foundry/orchestration/test_lifecycle_events.py`

### 2a. RED

```python
def test_run_aborted_event_value():
    assert LifecycleEvent.RUN_ABORTED.value == "run_aborted"
```

### 2b. GREEN

Add after `RUN_FAILED`:

```python
    RUN_ABORTED = "run_aborted"
```

### 2c. Verify

```
pdm run test-unit -- tests/agent_foundry/orchestration/test_lifecycle_events.py -q
```

---

## Task 3 — `RunEndedEvent` carries `outcome: RunOutcome`

**File:** `src/agent_foundry/orchestration/run_context.py`
**Test:** `tests/agent_foundry/orchestration/test_run_context_hooks.py`
(where `RunEndedEvent` is already exercised)

### 3a. RED

```python
def test_run_ended_event_defaults_no_outcome(run_context):
    ev = RunEndedEvent(run_context=run_context)
    assert ev.outcome is None
    assert ev.exception is None
    assert ev.output is None

def test_run_ended_event_carries_aborted_outcome(run_context):
    ev = RunEndedEvent(run_context=run_context, outcome=RunAborted(reason="declined"))
    assert isinstance(ev.outcome, RunAborted)
    assert ev.outcome.reason == "declined"
```

### 3b. GREEN

Add the field (after `output`):

```python
    outcome: RunOutcome | None = None
```

Import `RunOutcome` from `agent_foundry.orchestration.run_outcome`. Extend the
class docstring's terminal-state table from two rows to four (completed / aborted
/ backstop / crash) describing the `(exception, output, outcome)` triple per D5.

> Watch the import direction: `run_context.py` importing `run_outcome.py` is a
> sibling import within `orchestration/`. `run_outcome.py` must NOT import
> `run_context.py` (it imports only `pydantic` + stdlib), so no cycle. Confirm at
> GREEN.

### 3c. Verify

```
pdm run test-unit -- tests/agent_foundry/orchestration/test_run_context_hooks.py -q
pdm run typecheck
```

---

## Task 4 — Runner returns `RunOutcome` (core change)

**File:** `src/agent_foundry/orchestration/runner.py`
**Test:** `tests/agent_foundry/compiler/test_run_primitive_plan.py`

### 4a. RED

Add tests covering all four terminal conditions. Reuse the ABORT/never-converge
`Retry` fixtures from `tests/agent_foundry/primitives/test_retry_resolver_e2e.py`
(lift the minimal plan builder, or import it).

```python
async def test_completed_returns_run_completed(...):
    result = await run_primitive_plan(_plan_sequence(), ...)
    assert isinstance(result, RunCompleted)
    assert isinstance(result.output, PlanOutput)
    assert result.output.x == 2
    types = _lifecycle_types(run_dir)
    assert LifecycleEvent.RUN_ENDED.value in types

async def test_resolver_abort_returns_run_aborted(...):
    """ABORT -> RunAborted (does NOT raise); terminal event RUN_ABORTED."""
    result = await run_primitive_plan(_plan_with_abort_resolver("cannot-converge"), ...)
    assert isinstance(result, RunAborted)
    assert result.reason == "cannot-converge"
    types = _lifecycle_types(run_dir)
    assert LifecycleEvent.RUN_ABORTED.value in types
    assert LifecycleEvent.RUN_FAILED.value not in types

async def test_abort_on_run_ended_hook_sees_outcome(...):
    captured = []
    await run_primitive_plan(..., on_run_ended=[captured.append])
    (ev,) = captured
    assert isinstance(ev.outcome, RunAborted)
    assert ev.outcome.reason == "cannot-converge"
    assert ev.exception is None

async def test_backstop_returns_run_failed_backstop(...):
    """ResolverDidNotConvergeError -> RunFailed(BACKSTOP), does NOT raise;
    terminal event RUN_FAILED."""
    result = await run_primitive_plan(_plan_that_never_converges(), ...)
    assert isinstance(result, RunFailed)
    assert result.error_kind is FailureKind.BACKSTOP
    types = _lifecycle_types(run_dir)
    assert LifecycleEvent.RUN_FAILED.value in types
    assert LifecycleEvent.RUN_ABORTED.value not in types

async def test_crash_returns_run_failed_crash(...):
    """A FunctionAction that raises RuntimeError -> RunFailed(CRASH),
    does NOT raise; terminal event RUN_FAILED."""
    result = await run_primitive_plan(_plan_with_raising_action("boom"), ...)
    assert isinstance(result, RunFailed)
    assert result.error_kind is FailureKind.CRASH
    assert result.error_type == "RuntimeError"
    assert "boom" in result.message
```

> **Fixture assumption (D4a):** `_plan_that_never_converges()` is a `Retry` whose
> resolver always returns RETRY and whose body never passes `until`, with a small
> backstop ceiling so `ResolverDidNotConvergeError` trips. Confirm the actual
> field name on the `Retry` model (e.g. `resolver_max_reentries`) when writing.

### 4b. GREEN

Replace the seam with full outcome classification — no re-raise on any path:

```python
caught_exc: BaseException | None = None
final_output: BaseModel | None = None
outcome: RunOutcome
try:
    graph = compile_runtime_plan(plan)
    result_dict = await graph.ainvoke(initial_state.model_dump())
    final_output = root_out.model_validate(result_dict)
    outcome = RunCompleted(output=final_output)
except RetryAborted as aborted:
    outcome = RunAborted(reason=aborted.reason)
except ResolverDidNotConvergeError as backstop:
    caught_exc = backstop
    outcome = RunFailed(
        error_kind=FailureKind.BACKSTOP,
        error_type=type(backstop).__name__,
        message=str(backstop),
    )
except BaseException as exc:
    caught_exc = exc
    outcome = RunFailed(
        error_kind=FailureKind.CRASH,
        error_type=type(exc).__name__,
        message=str(exc),
    )
finally:
    if isinstance(outcome, RunAborted):
        terminal = LifecycleEvent.RUN_ABORTED
    elif isinstance(outcome, RunFailed):
        terminal = LifecycleEvent.RUN_FAILED
    else:
        terminal = LifecycleEvent.RUN_ENDED
    # error_kind rides the RUN_FAILED record so render_summary reads one field (D7a).
    lifecycle.append(
        terminal,
        run_id=resolved_run_id,
        **({"error_kind": outcome.error_kind.value} if isinstance(outcome, RunFailed) else {}),
    )
    ...  # registry.shutdown_all, render_summary (unchanged ordering)
    _safe_invoke_hooks(
        run_ctx.on_run_ended,
        RunEndedEvent(
            run_context=run_ctx,
            exception=caught_exc,
            output=final_output,
            outcome=outcome,
        ),
        label="on_run_ended",
    )
    ...  # signal-handler removal, ContextVar reset, lifecycle.close, provider shutdown
return outcome
```

Notes:
- `return outcome` is placed **after** the `try/finally` (not inside `try`), so
  every terminal path returns the classified envelope and the finally block runs
  exactly once before the return.
- Clause ordering is load-bearing: `RetryAborted` and `ResolverDidNotConvergeError`
  must precede the broad `except BaseException`, else they fall into CRASH.
- Verify `lifecycle.append` accepts arbitrary kwargs for the `error_kind` payload
  (check `JsonlLifecycleWriter.append` signature); if it does not, add `error_kind`
  via whatever mechanism the writer uses for event fields, or fall back to D7a
  option (b) and drop the kwarg.

Change the signature: `-> BaseModel` becomes `-> RunOutcome`. Import
`RunOutcome`, `RunCompleted`, `RunAborted`, `RunFailed`, `FailureKind` from
`agent_foundry.orchestration.run_outcome`; import `RetryAborted` and
`ResolverDidNotConvergeError` from `agent_foundry.primitives.retry_types`.

Rewrite the `run_primitive_plan` docstring teardown paragraph (~lines 100–109) to
describe: returns one `RunOutcome`; never re-raises; the four-way terminal
classification and its lifecycle-event mapping.

### 4c. Verify

```
pdm run test-unit -- tests/agent_foundry/compiler/test_run_primitive_plan.py -q
pdm run typecheck
```

---

## Task 5 — `render_summary` three-way classification

**File:** `src/agent_foundry/orchestration/summary.py`
**Test:** `tests/agent_foundry/orchestration/test_summary.py`

### 5a. RED

```python
def test_summary_reports_aborted_outcome(tmp_path):
    # jsonl: RUN_STARTED ... RESOLVER_DISPOSITION(kind=abort, reason="declined") ... RUN_ABORTED
    render_summary(run_dir)
    text = (run_dir / "summary.txt").read_text()
    assert "aborted" in text
    assert "declined" in text          # abort reason surfaced
    assert "failed" not in text

def test_summary_reports_failed_with_error_kind(tmp_path):
    # jsonl: RUN_STARTED ... RUN_FAILED(error_kind="backstop")
    render_summary(run_dir)
    text = (run_dir / "summary.txt").read_text()
    assert "failed" in text
    assert "backstop" in text          # error_kind surfaced
```

(Mirror the existing jsonl-fixture style in `test_summary.py`.)

### 5b. GREEN

In `render_summary`:

- Add `run_aborted = False`, `abort_reason: str | None = None`,
  `failure_kind: str | None = None` accumulators.
- Branch on `LifecycleEvent.RUN_ABORTED.value`: set `run_ended_at = ts`,
  `run_aborted = True`.
- On `LifecycleEvent.RUN_FAILED.value`: also capture
  `failure_kind = record.get("error_kind")` (D7a).
- On `LifecycleEvent.RESOLVER_DISPOSITION.value` with `kind == "abort"`: capture
  `abort_reason = record.get("reason")`.
- Replace the two-way status with three-way:
  `"aborted"` if `run_aborted`, else `"failed"` if `run_failed`, else
  `"completed"`.
- When aborted and `abort_reason`, append an `Abort reason: <reason>` line.
- When failed and `failure_kind`, append a `Failure kind: <failure_kind>` line.

### 5c. Verify

```
pdm run test-unit -- tests/agent_foundry/orchestration/test_summary.py -q
```

---

## Task 6 — Update callers + full-suite regression

### 6a. Production caller: `evals/agent_foundry_tasks.py`

**File:** `src/agent_foundry/evals/agent_foundry_tasks.py` (`build_run_primitive_plan_task`)

The inner `task` returns `await run_primitive_plan(...)` and is typed
`-> BaseModel`. Under the envelope it returns `RunOutcome`. Decide unwrapping
behavior for the eval task (assumption D6a):

- On `RunCompleted`: return `outcome.output` (the eval expects the product model).
- On `RunFailed`: raise — evals must surface a failed case as a failure. Map back
  to an exception here (e.g. `raise RuntimeError(outcome.message)` or re-raise a
  reconstructed error). The envelope removed the runner's re-raise; the *eval
  boundary* re-introduces it because the Inspect `Task` contract is exception-based.
- On `RunAborted`: an eval case should not abort; treat as a failure (raise) or
  surface as an explicit failed result. Chosen: raise with the abort reason.

Add a focused test in the evals test module asserting the task unwraps
`RunCompleted.output` and raises on `RunFailed`. (Locate via the existing evals
task tests; if none cover this path, add one mirroring the module's style.)

> This is the only **production** caller. `mlflow_adapter`, `evals/cli.py`,
> `telemetry`, `registry` reference `run_primitive_plan` only in docstrings — no
> code edit.

### 6b. Test callers that consume the return value (unwrap `RunCompleted.output`)

Each of these asserts on the *bare* return today and must unwrap:

- `tests/agent_foundry/compiler/test_run_primitive_plan.py`
  - `test_happy_path...` (~line 182): `assert isinstance(result, PlanOutput)` →
    `assert isinstance(result, RunCompleted); assert isinstance(result.output, PlanOutput); assert result.output.x == 2`.
- `tests/agent_foundry/integration/test_end_to_end.py`
  - ~line 201–203: `isinstance(result, StateC)` / `result.verified` /
    `result.headline` → unwrap via `result.output`. (Integration test; gated, but
    update for type-correctness.)
- `tests/agent_foundry/integration/test_mcp_tool_execution.py`
  - ~line 131–132: `isinstance(result, _Output)` / `result.echoed_word` →
    unwrap via `result.output`.

### 6c. Test callers that assert the runner RE-RAISES (behavior change, D6)

These currently wrap the call in `pytest.raises(...)`. Under D6 the runner returns
`RunFailed` instead. Update each to assert on the returned `RunFailed`:

- `tests/agent_foundry/orchestration/test_run_context_hooks.py`
  - `test_..._on_run_ended_with_exception_and_none_output_on_failure` (~line 151):
    drop `pytest.raises`; assert `isinstance(result, RunFailed)`,
    `result.error_kind is FailureKind.CRASH`, and the hook event still carries
    `exception` (a `RuntimeError`) + `output is None` + `outcome` a `RunFailed`.
  - `test_..._writes_run_failed_lifecycle_event` (~line 186): drop `pytest.raises`;
    keep the `RUN_FAILED` jsonl assertion.
  - Audit the rest of this file for other `pytest.raises` around
    `run_primitive_plan`.
- `tests/agent_foundry/orchestration/test_runner_telemetry.py`
  - `test_..._cleans_up_run_dir_when_build_tracer_provider_raises` (~line 177):
    this raises **before** the try/except seam (during `build_tracer_provider`, in
    the pre-graph setup), so it still propagates — **leave it raising**. Confirm
    the raise origin is pre-seam when updating; do not convert this one.

> **Audit step (load-bearing):** before finishing, grep the test tree for
> `pytest.raises(` within ~5 lines of `run_primitive_plan(` and classify each as
> pre-seam (still raises: telemetry-setup failures) vs. in-graph (now returns
> `RunFailed`). Only in-graph ones change.

### 6d. Full unit + typecheck regression

```
pdm run test-unit
pdm run typecheck
```

All unit tests green, zero pyright errors. The in-graph resolver e2e tests
(`test_retry_resolver_e2e.py`) use `_compile_and_run` (not `run_primitive_plan`)
and still expect `RetryAborted` / `ResolverDidNotConvergeError` to raise inside
the graph — they must stay **green and unchanged**.

---

## Task 7 — Docstring refresh (REFACTOR)

- `RetryAborted` docstring in `retry_types.py`: it currently says *"Terminates the
  run via the raise path (clean-signal variant deferred)."* Update to: an internal
  unwind signal the runner catches and converts to `RunAborted`; it does not
  escape `run_primitive_plan`. (Keep it about *this* type's contract per the
  comment-discipline rule; state only the load-bearing fact that it is caught, not
  the runner's full internals.)
- `ResolverDidNotConvergeError` docstring: note it is caught by the runner and
  surfaced as `RunFailed(error_kind=BACKSTOP)` (one line; load-bearing).
- Confirm the `run_primitive_plan` and `RunEndedEvent` docstring edits read
  correctly.

---

## Completion criteria

- [ ] `orchestration/run_outcome.py` defines `RunOutcome`, `RunOutcomeKind`,
      `FailureKind`, `RunCompleted`, `RunAborted`, `RunFailed`; union round-trips.
- [ ] `LifecycleEvent.RUN_ABORTED` exists (`"run_aborted"`).
- [ ] `RunEndedEvent.outcome: RunOutcome | None` added; `exception`/`output`
      back-compat preserved.
- [ ] `run_primitive_plan` returns `RunOutcome`, never re-raises an in-graph
      exception; writes the correct terminal event per outcome.
- [ ] ABORT → `RunAborted` + `RUN_ABORTED`; backstop → `RunFailed(BACKSTOP)` +
      `RUN_FAILED`; crash → `RunFailed(CRASH)` + `RUN_FAILED`; success →
      `RunCompleted` + `RUN_ENDED`.
- [ ] `render_summary` reports completed / aborted / failed, with abort reason and
      failure `error_kind` surfaced.
- [ ] `evals/agent_foundry_tasks.py` unwraps `RunCompleted.output` and raises on
      `RunFailed`.
- [ ] All return-consuming and re-raise-asserting tests updated; pre-seam telemetry
      raise test left raising.
- [ ] In-graph resolver e2e tests unchanged and green.
- [ ] `pdm run test-unit` and `pdm run typecheck` clean.

---

## Open Questions / Decisions for Review

1. **(D6) Runner no longer re-raises — primary decision.** The envelope makes the
   FAILED path *return* `RunFailed` rather than propagate the exception. This is
   what makes `RunOutcome` a true single terminal envelope, but it changes a
   long-standing contract and touches several tests (Task 6c). Alternative: keep
   re-raising CRASH/BACKSTOP and only return for COMPLETED/ABORTED — rejected
   because callers would still pattern-match exceptions for failures. **Confirm the
   no-re-raise contract.**

2. **(D2) Module placement.** `RunOutcome` lives in
   `orchestration/run_outcome.py` (NOT `primitives/retry_types.py`) to keep #70
   disjoint from #62's `primitives/` + `primitive_compiler.py` churn. Confirm.

3. **(D1a) Discriminator typing.** `kind: RunOutcomeKind = RunOutcomeKind.VARIANT`
   vs. the `Literal[...]` fallback if the pinned Pydantic rejects StrEnum
   discriminators. Resolved empirically at GREEN. Confirm the convention reading.

4. **(D1c / D5) Where the live exception lives.** `RunFailed` carries
   string-reconstructable fields (`error_kind`, `error_type`, `message`), not the
   live `BaseException`; the traceback-bearing object still reaches `on_run_ended`
   via `RunEndedEvent.exception`. Confirm this split is acceptable (vs. e.g.
   stashing the exception on `RunFailed` with `arbitrary_types_allowed`).

5. **(D4) Backstop vs. crash on the wire.** Both map to `RUN_FAILED`; the
   distinction is the typed `RunFailed.error_kind` and the `error_kind` field on
   the `RUN_FAILED` record (D7a). No dedicated `RUN_BACKSTOP_TRIPPED` event.
   Confirm.

6. **(D7a) `error_kind` on the lifecycle record.** Task 4 writes `error_kind` into
   the `RUN_FAILED` jsonl record so `render_summary` reads one field. Requires the
   lifecycle writer to accept the extra field; if it doesn't, fall back to
   inferring backstop from a `ResolverDidNotConvergeError`-shaped record. Confirm
   the writer's field-passing mechanism.

7. **(D6a) Eval-boundary unwrapping.** `build_run_primitive_plan_task` unwraps
   `RunCompleted.output` and **raises** on `RunFailed`/`RunAborted` (the Inspect
   `Task` contract is exception-based). Confirm raising at the eval boundary is the
   right adaptation.

8. **(#66 / #62 collision)** #70's only behavioral edit is `runner.py`'s terminal
   block + new `orchestration/` files. The typed-terminal-node-in-compiler is
   deferred to #66. #62's `primitive_compiler.py` work is disjoint. Reviewer to
   confirm no line-level conflict if these land close together.

9. **(#69)** The labeled three-way summary outcome satisfies #69's dependency on a
   classified terminal result. Confirm #69 needs nothing beyond
   completed/aborted/failed + reason + error_kind.
