# Implementation Plan: Operator-Guided Retry (Resolver Seat on `Retry`)

**Feature:** Operator-Guided Retry
**Spec:** `docs/archipelago/2026-05-24-operator-guided-retry-feature-def.md` (revised 2026-05-30)
**Design principles:** `archipelago/docs/architecture-wins.md`
**Date:** 2026-05-30

> This plan **replaces** the earlier `GuidedRetry`-composite-primitive plan. There is **no new
> top-level primitive**. The capability is a backwards-compatible extension of `Retry` plus a new
> compiler topology. The `GuidedRetry` class must not reappear.

---

## 0. Verification of the central architectural claim (done before planning)

The feature def's Implementation Notes assert the post-exhaustion resolver re-entry must be a **graph
cycle of outer-graph nodes**, not a Python loop inside the retry node, because a `GateAction` only
interrupts/resumes as an outer-graph node and a gate inside a Python loop loses loop-carried state on
resume. **This was independently confirmed against the compiler. The claim holds.** Evidence:

- `_compile_retry` (`src/agent_foundry/compiler/primitive_compiler.py:491-558`) is a single graph
  node `retry_node` whose Python `for attempt_num in range(max_attempts)` loop calls
  `compiled_body.ainvoke(...)`. The body subgraph is compiled at **line 477** via
  `body_graph.compile()` **with no checkpointer** — it is an isolated sub-graph.
- `_compile_gate_action` (`primitive_compiler.py:567-579`) registers `gate_node` and appends its id
  to `ctx.gate_ids` (line 578). The node itself is a pass-through; the *pause* is produced elsewhere.
- Only `compile_runtime_plan` (`primitive_compiler.py:205-212`) turns `ctx.gate_ids` into the
  top-level graph's `interrupt_before` list and injects a `MemorySaver` checkpointer — and only for
  the **outer** graph returned by `graph.compile(**compile_kwargs)`.

Consequences that make the in-node-loop approach impossible for a gate resolver:

1. A gate compiled inside the retry node's body subgraph never reaches the outer
   `interrupt_before`/`MemorySaver` wiring, so it cannot pause and resume at all.
2. LangGraph interrupt/resume re-enters a node **from the top**. The retry node's Python locals
   (`current_state`, `attempt_failures`, the consecutive-RETRY counter) are not persisted channels,
   so a resume would wipe them.

Therefore the post-exhaustion phase is wired as real outer-graph nodes:

```
retry_node --(exhausted)--> resolver_node --(RETRY)--> body_once_node --(until NOT_PASSED)--> resolver_node
                               | ACCEPT  --> downstream (END/next)        --(until PASSED)----> downstream
                               | ABORT   --> abort_node (raises today; see §1)
```

The automated phase stays an in-node loop (its body has no gate and never interrupts). The resolver
and the single re-entry body run are outer-graph nodes so a `GateAction` resolver pauses correctly
and the consecutive-RETRY backstop counter survives resume as a **declared state channel**.

A RETRY re-run that **passes** `until` exits successfully — it does **not** bounce back to the
resolver. This mirrors the automated loop's exit semantics (pass ⇒ done) and avoids a redundant
operator round-trip on the success the operator just asked for:

```
body_once_node --(until PASSED)--> downstream (same exit as the automated pass path)
               --(until NOT_PASSED)--> resolver_node
```

---

## 1. Gaps in the feature def resolved before planning

These are stated up front so the tasks below are buildable. None contradicts the def's architectural
notes; they reconcile its vocabulary with the code as it actually stands today.

1. **`exception_policy` member names.** The def and the shipped enum (`models.py:67-77`) agree:
   `RetryExceptionPolicy.PROPAGATE | RetryExceptionPolicy.CATCH_AND_CONTINUE`. **Resolution:** reuse
   the existing enum unchanged. `CATCH_AND_CONTINUE` consumes the attempt, restores pre-attempt state,
   and continues — i.e. a body raise becomes a `NOT_PASSED` attempt. We do **not** introduce a
   `TREAT_AS_NOT_PASSED` member: renaming/adding to a landed enum is a breaking change the def does not
   authorize, and the def's Dependencies section says the policy is "already landed". Plan text and
   all AC tests use the real member name `CATCH_AND_CONTINUE`.

2. **`AttemptOutcome`.** The def describes a binary per-attempt outcome `PASSED | NOT_PASSED`. No such
   type exists today; the in-node loop branches directly on `until_fn(...)` and on exception. We
   **introduce `AttemptOutcome(StrEnum)`** as a named boundary value (Task 1) and use it in the
   resolver-phase `body_once_node` so the resolver and tests can branch on a single axis, satisfying
   the def's "one vocabulary per axis" principle. The automated in-node loop is refactored to produce
   the same value so AC #8's "no separate guided-iteration code path" is structurally true.

3. **`on_exhaustion` is removed, not kept alongside.** `Retry` carries a pre-existing
   `on_exhaustion: Callable | None` (`models.py:93-100`). It and the new resolver seat are **the same
   seat** — identical trigger (max_attempts spent without passing) and identical question (what to do
   now). Two fields for one concern is exactly the conflation this redesign removes. **Resolution:**
   **delete `on_exhaustion` from `Retry`** (Task 2). It is consumed only by Archipelago today, and the
   def rates backwards-compat low-priority; its old "return state" / "raise" behaviors map cleanly
   onto a `FunctionAction` resolver returning `ACCEPT` / `ABORT`. With the field gone there is nothing
   to be mutually exclusive with, so **no mutual-exclusion validator rule** is added.

4. **Fail-closed default vs. today's silent exit.** Today, `_compile_retry` with no `on_exhaustion`
   exits silently (`primitive_compiler.py:557-558`). The def mandates fail-closed: **unset resolver
   ⇒ ABORT on exhaustion**, keyed off the single field only. **Resolution:** when
   `on_max_attempts_resolver is None`, exhaustion now routes to the abort node — there is no
   `on_exhaustion` branch to consider. AC #4's "behaves exactly as today when the body passes within
   max_attempts" is preserved because the pass path never reaches exhaustion. The silent-exit default
   is removed; this is the one intentional behavior change and is called out in the completion
   checklist and a test (Task 4).

5. **ABORT termination mechanism.** The def is explicit (Scope Boundaries, last bullet; Implementation
   Notes): a **clean run-termination runtime signal is deferred to a separate spec**. `ABORT`
   therefore terminates via the **raise/error path** today — the same mechanism the runaway backstop
   uses. The plan implements `ABORT` as a raised `RetryAborted` exception and the backstop as a
   *distinct* raised `ResolverDidNotConvergeError`. AC #9 asserts the two are distinguishable. We do
   **not** implement a clean terminal signal.

6. **`max_interventions` is gone.** The old plan's second budget counter does not exist in this
   design. `max_attempts` bounds the automated phase only and is never refreshed. The only post-
   exhaustion bound is the **safety backstop ceiling** (a high default), which is a safety invariant,
   not a budget the resolver reasons about (def "Runaway protection").

---

## Files touched

| File | Change |
|---|---|
| `src/agent_foundry/primitives/retry_types.py` | Add `AttemptOutcome` StrEnum; add `DispositionKind` enum + a single **non-generic** `ResolverDisposition` model carrying `kind` + optional `reason` (**no `state` payload** — it is a pure routing signal); add `RetryAborted`, `ResolverDidNotConvergeError` exceptions. **Reuse** existing `RetryExhaustionReason` + `AttemptFailure` for metadata — add no parallel reason enum. Note in one line that `RetryExhaustion[I]` becomes an unused public type once `on_exhaustion` is gone |
| `src/agent_foundry/primitives/models.py` | Extend `Retry`: add `on_max_attempts_resolver: Primitive | None` and `resolver_max_reentries: int` (backstop ceiling); **remove `on_exhaustion`**; add `model_rebuild` if needed |
| `src/agent_foundry/primitives/__init__.py` | Export `AttemptOutcome`, the disposition types, and the two new exceptions (and `RetryExhaustionReason`/`AttemptFailure` if not already exported) |
| `src/agent_foundry/primitives/validators.py` | Extend `_validate_retry`: resolver primitive recursion + type rules; backstop ceiling `ge=1` (no mutual-exclusion rule — `on_exhaustion` is gone) |
| `src/agent_foundry/compiler/primitive_compiler.py` | Rework `_compile_retry` to emit the resolver cycle (resolver_node / body_once_node / abort_node); `body_once_node` evaluates `until` and exits on PASS; route on `disposition.kind` using the resolver node's **output state** as the continue/accept state (disposition carries no state). Add a **pre-pass** (`_collect_retry_channels`) that walks the plan tree BEFORE `_derive_state_type` and folds every Retry's namespaced backstop + metadata channels into the outer state schema. Fail-closed default |
| `tests/agent_foundry/primitives/test_retry_types.py` | `AttemptOutcome` + `ResolverDisposition` (routing signal) + exception tests |
| `tests/agent_foundry/primitives/test_primitive_models.py` | `Retry` field-extension construction tests |
| `tests/agent_foundry/primitives/test_primitive_validators.py` | resolver validator tests |
| `tests/agent_foundry/primitives/test_retry_resolver.py` (new) | compiler-level AC tests #1-#4, #8, #9, plus exhaustion-metadata channel reads |
| `tests/agent_foundry/primitives/test_retry_resolver_e2e.py` (new) | synthetic end-to-end, non-gate resolver, AC #5, #6, #7 |

---

## Task graph

```
Task 1 (AttemptOutcome + ResolverDisposition routing signal + exceptions in retry_types.py;
        reuse existing RetryExhaustionReason/AttemptFailure)
  └─► Task 2 (Retry field extension + on_exhaustion removal in models.py + exports;
       reuse existing RetryExhaustionReason/AttemptFailure)
        ├─► Task 3 (validator extension)        ──┐
        └─► Task 4 (compiler: resolver cycle)   ──┤
              └─► Task 4b (exhaustion metadata   ──┼─► Task 5 (e2e: non-gate resolver, AC #5/#6/#7)
                   into state, resolver reads it) │
                                                  │
        AC #8 / AC #9 land inside Task 4's test file (test_retry_resolver.py)
```

Tasks 3 and 4 are independent of each other after Task 2. Task 4b depends on Task 4 (it extends the
same `_compile_retry` cycle). Task 5 depends on Task 4b. Each task is strict TDD: failing test first,
then implementation, then the exact `pdm` verification command.

---

## Task 1 — `AttemptOutcome`, the `ResolverDisposition` routing signal, and the termination/backstop exceptions

**File:** `src/agent_foundry/primitives/retry_types.py`
**Test file:** `tests/agent_foundry/primitives/test_retry_types.py`

### What to build

1. `AttemptOutcome(StrEnum)` — binary, one axis ("did this attempt pass `until`?"):
   - `PASSED = "passed"`
   - `NOT_PASSED = "not_passed"`

   Two members only. Per the def's orthogonality principle, exception handling is **not** a third
   member — `exception_policy` maps a raise to `NOT_PASSED`; it does not add an `ERRORED` outcome.

1b. **Reuse the existing `RetryExhaustionReason` for exhaustion metadata — do NOT invent a new
   enum.** `retry_types.py:11-23` already defines `RetryExhaustionReason(StrEnum)` with
   `CONDITION_NOT_MET` (all attempts ran, none passed), `BODY_EXCEPTIONS` (every attempt raised under
   `CATCH_AND_CONTINUE`), and `MIXED` (some raised, some ran without passing). This is strictly richer
   than the binary "clean non-pass vs. all-errored" distinction the def's Implementation Notes call
   for, and `BODY_EXCEPTIONS` is exactly the "all attempts errored ⇒ justifies ABORT" input. Reuse it
   verbatim; `AttemptFailure` (`retry_types.py:26-30`) is likewise reused for the per-attempt failure
   records. Task 4b writes these into state.

   The enclosing `RetryExhaustion[I]` wrapper (`retry_types.py:33-47`) existed only to feed the removed
   `on_exhaustion` callable. With that hook gone the wrapper has no consumer and **becomes an unused
   public type**. Leave it in place (harmless, out of scope to delete) but do **not** route it through
   state — a resolver reads the flat namespaced channels (reason + failures), not the wrapper. Update
   the module docstring only if trivially stale; otherwise leave it.

2. The disposition is a **lightweight routing signal — not a wrapper carrying a state payload.** It
   carries `kind` (ACCEPT/ABORT/RETRY) and an optional `reason` (used for ABORT). It does **not**
   carry `state`. The "state to continue/accept with" is simply the resolver node's normal output
   state, which already lives in graph state (the resolver is a compiled outer-graph node that merges
   its output like any other node); there is no need to nest it inside the disposition.

   This makes the resolver→disposition contract **uniform across every primitive kind** and removes the
   `GateAction` translation problem: a `FunctionAction`/`AICall`/`AgentAction` resolver sets `kind` in
   its normal output model; a `GateAction` resolver's parser sets `kind` and writes the operator's
   findings into existing state fields. No translation `Sequence`, no operator "typing a full state
   model", no nested-state-through-flat-channels concern.

   Because `kind` is a single field on one model (not a discriminator across structurally distinct
   variants), a tagged discriminated union is unnecessary. Use **one non-generic model**:

   ```python
   class DispositionKind(StrEnum):
       ACCEPT = "accept"
       ABORT = "abort"
       RETRY = "retry"

   class ResolverDisposition(BaseModel):
       """Routing signal a resolver primitive emits when the automated phase exhausts.

       Pure routing — carries no state. The state the compiler continues/accepts/re-runs
       with is the resolver node's own merged output state, already in graph state. The
       compiler reads ``kind`` to route; ``reason`` is the operator's ABORT explanation
       (ignored for ACCEPT/RETRY).
       """

       kind: DispositionKind
       reason: str = ""
   ```

   `kind` has no default — a resolver must state its disposition explicitly. `reason` defaults empty
   and is only meaningful on ABORT (it is threaded into `RetryAborted`).

3. Two exceptions (distinct types — AC #9 requires they be distinguishable):
   ```python
   class RetryAborted(Exception):
       """Raised when a resolver returns ABORT. Carries the abort reason.
       Terminates the run via the raise path (clean-signal variant deferred)."""
       def __init__(self, reason: str): ...

   class ResolverDidNotConvergeError(Exception):
       """Raised when consecutive RETRY re-entries hit the safety backstop ceiling.
       A safety invariant trip, NOT an intentional abort."""
       def __init__(self, ceiling: int): ...
   ```

### TDD steps

**Failing tests first** (`test_retry_types.py`):

```python
from enum import StrEnum
import pytest
from pydantic import BaseModel, ValidationError
from agent_foundry.primitives.retry_types import (
    AttemptOutcome, RetryExhaustionReason, DispositionKind,
    ResolverDisposition, RetryAborted, ResolverDidNotConvergeError,
)

class S(BaseModel):
    n: int = 0

def test_attempt_outcome_is_binary_str_enum():
    assert issubclass(AttemptOutcome, StrEnum)
    assert {m.value for m in AttemptOutcome} == {"passed", "not_passed"}

def test_existing_exhaustion_reason_reused_not_redefined():
    # Reuse the landed enum; no new parallel reason type is introduced.
    assert {m.value for m in RetryExhaustionReason} == {
        "condition_not_met", "body_exceptions", "mixed",
    }

def test_disposition_kind_members():
    assert {m.value for m in DispositionKind} == {"accept", "abort", "retry"}

def test_disposition_is_pure_routing_signal_no_state():
    # The disposition carries kind + optional reason only. No state payload —
    # the continue/accept state is the resolver node's own output state.
    assert "state" not in ResolverDisposition.model_fields
    assert set(ResolverDisposition.model_fields) == {"kind", "reason"}

def test_disposition_kind_required_reason_optional():
    d = ResolverDisposition(kind=DispositionKind.RETRY)
    assert d.kind == DispositionKind.RETRY
    assert d.reason == ""
    with pytest.raises(ValidationError):
        ResolverDisposition()  # kind has no default — must be stated

def test_abort_disposition_carries_reason():
    d = ResolverDisposition(kind=DispositionKind.ABORT, reason="operator gave up")
    assert d.kind == DispositionKind.ABORT
    assert d.reason == "operator gave up"

def test_disposition_round_trips_through_json():
    d = ResolverDisposition.model_validate({"kind": "accept"})
    assert d.kind == DispositionKind.ACCEPT

def test_retry_aborted_is_distinct_from_backstop():
    assert not issubclass(RetryAborted, ResolverDidNotConvergeError)
    assert not issubclass(ResolverDidNotConvergeError, RetryAborted)
    assert RetryAborted("r").reason == "r"
    assert ResolverDidNotConvergeError(50).ceiling == 50
```

**Implement:** Append `AttemptOutcome`, the disposition variants, the union helper, and the two
exceptions to `retry_types.py`. `RetryExhaustionReason` and `AttemptFailure` already exist — reuse
them, add nothing parallel.

### Verification

```bash
pdm run pytest tests/agent_foundry/primitives/test_retry_types.py -x
```

---

## Task 2 — Extend `Retry` with the resolver seat + backstop ceiling, remove `on_exhaustion`, and exports

**Files:** `src/agent_foundry/primitives/models.py`, `src/agent_foundry/primitives/__init__.py`
**Test file:** `tests/agent_foundry/primitives/test_primitive_models.py`

### What to build

Add two fields to the existing `Retry` (do **not** create a new class):

```python
on_max_attempts_resolver: Primitive | None = None
"""Primitive consulted when the automated loop exhausts max_attempts without until() passing.

The resolver runs as a normal outer-graph node and merges its output into graph state like any
other node. Its output model must declare a ``disposition: ResolverDisposition`` field; the compiler
reads that field's ``kind`` (ACCEPT/ABORT/RETRY) to route and uses the resolver node's own output
state as the continue/accept state. The disposition is a pure routing signal — it carries no state.
A GateAction resolver satisfies this by having its parser set ``kind`` and write findings into
existing state fields. When None, exhaustion is fail-closed (ABORT)."""

resolver_max_reentries: int = Field(default=50, ge=1)
"""Safety backstop: max consecutive RETRY re-entries before raising
ResolverDidNotConvergeError. A safety invariant, not a budget the resolver reasons about."""
```

**Remove the `on_exhaustion: Callable | None` field** (`models.py:93-100`) — the resolver seat is its
sole replacement (Gaps §3). Find and update its consumers: it is read only by `_compile_retry`
(handled in Task 4) and by Archipelago (out of this repo; backwards-compat is low-priority per the
def). Search the repo for `on_exhaustion` before deleting so no in-repo reference is orphaned.

`max_attempts`, `until`, `body`, and `exception_policy` are unchanged. A `Retry.model_rebuild()` is
already present (`models.py:260`); confirm `Primitive` forward-ref still resolves with the new field.
Export `AttemptOutcome`, `DispositionKind`, `ResolverDisposition`, `RetryAborted`,
`ResolverDidNotConvergeError` from `__init__.py` and add to `__all__` (plus
`RetryExhaustionReason`/`AttemptFailure` if not already exported, since resolvers and tests now read
them).

### TDD steps

**Failing tests first** (`test_primitive_models.py`):

```python
from agent_foundry.primitives.models import Retry, FunctionAction
from agent_foundry.primitives.retry_types import DispositionKind, ResolverDisposition

class S(BaseModel):
    n: int = 0
    verdict: str = ""

def _body():
    return FunctionAction[S, S](function=lambda s: S(n=s.n + 1))

def test_retry_resolver_seat_defaults_none():
    r = Retry[S, S](max_attempts=3, until=lambda s: s.n >= 3, body=_body())
    assert r.on_max_attempts_resolver is None
    assert r.resolver_max_reentries == 50  # high default

def test_retry_accepts_resolver_primitive():
    resolver = FunctionAction[S, S](function=lambda s: s)
    r = Retry[S, S](max_attempts=1, until=lambda s: False, body=_body(),
                    on_max_attempts_resolver=resolver)
    assert r.on_max_attempts_resolver is resolver

def test_resolver_max_reentries_ge_1():
    with pytest.raises(ValidationError):
        Retry[S, S](max_attempts=1, until=lambda s: False, body=_body(),
                    resolver_max_reentries=0)

def test_retry_backwards_compatible_without_resolver():
    # Existing construction path unchanged.
    r = Retry[S, S](max_attempts=2, until=lambda s: s.n >= 2, body=_body())
    assert r.on_max_attempts_resolver is None

def test_on_exhaustion_field_removed():
    # The old callable seat is gone; resolver seat is its sole replacement.
    assert "on_exhaustion" not in Retry.model_fields
    with pytest.raises(ValidationError):
        Retry[S, S](max_attempts=1, until=lambda s: False, body=_body(),
                    on_exhaustion=lambda ex: S())

def test_disposition_types_exported_from_package():
    from agent_foundry.primitives import DispositionKind, ResolverDisposition
    from agent_foundry.primitives import RetryAborted, ResolverDidNotConvergeError, AttemptOutcome
    assert ResolverDisposition is not None
```

**Implement:** Add the two fields and the exports.

### Verification

```bash
pdm run pytest tests/agent_foundry/primitives/test_primitive_models.py -x -k "resolver or disposition or backwards"
pdm run python -c "from agent_foundry.primitives import ResolverDisposition, ResolverDidNotConvergeError; print('ok')"
```

---

## Task 3 — Validator extension on `Retry`

**File:** `src/agent_foundry/primitives/validators.py`
**Test file:** `tests/agent_foundry/primitives/test_primitive_validators.py`

### What to build

Extend `_validate_retry` (do not add a new registered validator — the seat lives on `Retry`). Keep
the three existing body type rules (`validators.py:132-170`) unchanged. There is **no**
mutual-exclusion rule — `on_exhaustion` no longer exists, so there is nothing to be exclusive with.
Add:

1. **Resolver field availability:** when the resolver is set, its `resolver_in` fields must be a
   subset of `retry_in.model_fields` (the resolver sees state available at exhaustion, which is `I`
   since `body_in == body_out == retry_in == retry_out`). Reuse `_fields_available(resolver_in,
   set(retry_in.model_fields), "Retry resolver input")`.
2. **Recurse:** `validate_primitive(retry.on_max_attempts_resolver)` when set, so a gate resolver's
   `prompt_key` and a nested resolver's own rules are checked.

Do **not** assert anything about the resolver's *output* type here — the requirement that the
resolver's output model carries a `disposition: ResolverDisposition` field is a compiler-boundary
contract validated in Task 4 (the routing edge raises `PrimitiveCompilationError` if `disposition` is
absent or not coercible), not a flat-field-availability rule.

### TDD steps

**Failing tests first** (`test_primitive_validators.py`):

```python
from agent_foundry.primitives.validators import validate_primitive
from agent_foundry.primitives.models import Retry, FunctionAction, GateAction
from agent_foundry.primitives.errors import TypeMismatchError

class S(BaseModel):
    n: int = 0
    verdict: str = ""

def _body():
    return FunctionAction[S, S](function=lambda s: S(n=s.n + 1))

def test_validate_retry_with_function_resolver_ok():
    r = Retry[S, S](max_attempts=1, until=lambda s: False, body=_body(),
                    on_max_attempts_resolver=FunctionAction[S, S](function=lambda s: s))
    validate_primitive(r)  # no raise

def test_validate_retry_resolver_field_not_available():
    class Extra(BaseModel):
        n: int = 0
        unknown: str = ""
    r = Retry[S, S](max_attempts=1, until=lambda s: False, body=_body(),
                    on_max_attempts_resolver=FunctionAction[Extra, S](function=lambda e: S()))
    with pytest.raises(TypeMismatchError, match="resolver input"):
        validate_primitive(r)

def test_validate_retry_recurses_into_gate_resolver():
    # Gate resolver with a prompt_key absent from S must fail validation via recursion.
    bad_gate = GateAction[S, S](interaction="stdin", prompt_key="not_a_field")
    r = Retry[S, S](max_attempts=1, until=lambda s: False, body=_body(),
                    on_max_attempts_resolver=bad_gate)
    with pytest.raises(Exception):  # InvalidPromptKeyError from the gate validator
        validate_primitive(r)

def test_validate_retry_no_resolver_unchanged():
    r = Retry[S, S](max_attempts=2, until=lambda s: s.n >= 2, body=_body())
    validate_primitive(r)  # existing behaviour, no raise
```

**Implement:** Extend `_validate_retry`.

### Verification

```bash
pdm run pytest tests/agent_foundry/primitives/test_primitive_validators.py -x -k "resolver or retry"
pdm run pytest tests/agent_foundry/primitives/ -x   # no regressions
```

---

## Task 4 — Compiler: the resolver-cycle topology

**File:** `src/agent_foundry/compiler/primitive_compiler.py`
**Test file:** `tests/agent_foundry/primitives/test_retry_resolver.py` (new)

This is the load-bearing task. It implements the verified §0 topology.

### What to build

Rework `_compile_retry` so that it **always** compiles the **outer-graph cycle** for the
post-exhaustion phase (the resolver seat is the only exhaustion mechanism now). When
`retry.on_max_attempts_resolver is None` the cycle's resolver node is fail-closed (synthesizes
`ABORT`); when set, the resolver primitive occupies it. The old single-node silent-exit on exhaustion
is removed entirely.

**Unchanged automated phase.** The in-node loop (`primitive_compiler.py:491-526`) stays as-is for the
automated attempts, including `exception_policy == CATCH_AND_CONTINUE` rollback. Refactor the
pass/no-pass branch to compute an `AttemptOutcome` value so the **same** code path is reused by the
re-entry node (AC #8: no separate guided-iteration exception path). The automated phase's body
subgraph remains compiled with **no checkpointer** (line 477) — it has no gate.

**State widening — ordering matters (this was a bug in the earlier draft).** The backstop counter and
the exhaustion-metadata channels (Task 4b) must be **declared channels in the outer state schema** so
they survive a gate interrupt/resume and so LangGraph does not drop the keys the nodes return.

The earlier draft collected these into a `ctx.extra_channels` set "mirroring `gate_ids`" and surfaced
them in `compile_runtime_plan`. **That is too late and would silently drop the channels.** Verified
against the code:

- `compile_runtime_plan` (`primitive_compiler.py:194-212`) derives the outer state type at **line 197**
  (`state_type = _derive_state_type(root_in, root_out)`) and constructs the `StateGraph(state_type)` at
  **line 198** — *before* `_compile_node` runs at **line 201**.
- LangGraph **fixes the schema at `StateGraph` construction**; keys a node returns that were not
  declared in `state_type` are dropped on the merge. So any channel discovered *during* `_compile_node`
  (the way `gate_ids` is accumulated) cannot retroactively widen the already-built schema.
- `gate_ids` works post-hoc only because it feeds `interrupt_before`/`checkpointer` as **compile
  kwargs** at line 205-210, consumed by `graph.compile(...)` *after* node compilation. A state
  **channel** has no such late-binding seam — it must exist at line 197.

**Fix: a pre-pass that runs before `_derive_state_type`.** Add a module-level
`_collect_retry_channels(prim: Primitive, prefix: str) -> dict[str, Any]` that walks the plan tree
with the **same prefix-derivation rules the compilers use** and, for every `Retry` it finds, emits its
namespaced channels:

```python
def _retry_channels(prefix: str) -> dict[str, Any]:
    # prefix is the Retry node's own compile prefix (e.g. "root", "root_step_2_body").
    return {
        f"{prefix}__resolver_reentries": Any,    # backstop counter
        f"{prefix}__exhaustion_reason": Any,     # Task 4b
        f"{prefix}__attempt_failures": Any,      # Task 4b
    }
```

`_collect_retry_channels` recurses structurally, mirroring each compiler's child-prefix scheme exactly
(`Sequence` → `f"{prefix}_step_{i}"` per step; `Conditional` → `f"{prefix}_then"` / `f"{prefix}_else"`;
`Loop`/`Retry` → `f"{prefix}_body"`; the resolver seat → `f"{prefix}_resolver"`). When it reaches a
`Retry`, it records `_retry_channels(prefix)` **and** recurses into `retry.body` (prefix
`f"{prefix}_body"`) and `retry.on_max_attempts_resolver` (prefix `f"{prefix}_resolver"`) so nested
Retries are covered too.

`compile_runtime_plan` then folds the collected channels into the outer schema **before** building the
graph:

```python
state_type = _derive_state_type(root_in, root_out)
extra = _collect_retry_channels(root, "root")
if extra:
    merged = {**{n: Any for n in state_type.__annotations__}, **extra}
    state_type = TypedDict("PrimitiveState", merged, total=False)
graph = StateGraph(state_type)
```

**Prefix determinism — why the pre-pass and compilation agree.** Compile prefixes are a **pure
function of tree position**: the root is the literal `"root"` (`primitive_compiler.py:200`), and every
child prefix is derived solely from the parent prefix plus structural index/role
(`f"{ctx.prefix}_step_{i}"`, `f"{ctx.prefix}_body"`, `f"{ctx.prefix}_then"`, etc.). There is no
randomness, no counter, and no dependency on `gate_ids` accumulation order or on which sibling compiled
first. The pre-pass walks the identical tree from the identical root prefix `"root"` applying the
identical derivation rules, so each Retry's prefix in the pre-pass is byte-for-byte the prefix
`_compile_retry` later receives via `ctx.prefix`. The channels therefore line up by construction. A
test asserts a nested Retry (inside a `Sequence` step) gets its channels declared, which would fail if
the prefix schemes diverged.

**Nodes emitted (only when the resolver cycle is active):**

1. `retry_node` (`f"{ctx.prefix}_retry"`) — runs the automated in-node loop. On pass → exits to the
   downstream exit. On exhaustion → falls through to `resolver_node` via an unconditional edge.
   Initializes `state[backstop_key] = 0` on first exhaustion entry.
2. `resolver_node` (`f"{ctx.prefix}_resolver"`):
   - If the seat is **unset** (fail-closed default): a synthetic node writes
     `{"disposition": ResolverDisposition(kind=ABORT, reason="no resolver configured")}` into state, so
     the routing edge below sees an ABORT uniformly.
   - If set: the resolver primitive is compiled as a real outer-graph node via `_compile_node(graph,
     retry.on_max_attempts_resolver, ctx.child(f"{ctx.prefix}_resolver"))` so a `GateAction` resolver's
     id reaches the top-level `interrupt_before` and a `MemorySaver` is injected. The resolver merges
     its output into graph state like any node; its output model **must** declare a `disposition`
     field. The routing edge below reads `state["disposition"]`; if absent or not coercible to
     `ResolverDisposition`, raise `PrimitiveCompilationError` (shape contract).
   - **The disposition carries no state.** The state the cycle continues with is whatever the resolver
     node merged into graph state — its normal output. The routing edge reads only `kind` (+ `reason`
     for ABORT). A conditional edge routes on `disposition.kind`:
     - `ACCEPT` → route to the merge/exit node; downstream sees the resolver's merged output state
       (no copy of a nested `disposition.state` — there is none).
     - `ABORT` → `abort_node` (carrying `disposition.reason`).
     - `RETRY` → increment `state[backstop_key]`; if it **exceeds** `resolver_max_reentries`, route to
       a backstop branch that **raises `ResolverDidNotConvergeError(ceiling)`**; else route to
       `body_once_node` (continuing with the resolver's merged output state already in graph state).
3. `body_once_node` (`f"{ctx.prefix}_reentry"`) — runs the body **exactly once** (same compiled body
   subgraph, same `exception_policy`, same `AttemptOutcome` computation as the automated loop), then
   **evaluates `until` on the result**:
   - `until` **PASSED** → route to the **merge/exit node** — the same successful exit the automated
     pass path uses. A re-run that satisfies the condition exits successfully; it does **not** bounce
     back to the resolver for a redundant round-trip on the success just requested.
   - `until` **NOT_PASSED** → unconditional route back to `resolver_node` for the next disposition.

   This mirrors the automated loop's pass/no-pass exit semantics (AC #1: one body re-run per RETRY; AC
   #3: a re-run that still fails returns to the resolver; the pass-on-re-run case exits). Use a
   conditional edge keyed on the `AttemptOutcome` `body_once_node` computes.
4. `abort_node` (`f"{ctx.prefix}_abort"`) — raises `RetryAborted(reason)`. (Deferred clean-signal
   noted; today ABORT and the backstop both use the raise path but as **distinct** exception types.)

**Exit wiring.** `_compile_retry` must return a `CompileResult(entry_id, exit_id)` where `entry_id` is
`retry_node` and `exit_id` is a merge node that both the pass path and the ACCEPT path feed into, so
the parent can attach downstream nodes uniformly.

**No `on_exhaustion` branch.** The field is gone (Task 2). The existing single-node `on_exhaustion`
exhaustion handling (`primitive_compiler.py:528-555`) and the silent-exit default
(`primitive_compiler.py:557-558`) are both **deleted**. Exhaustion has exactly one path: the resolver
cycle, fail-closed to `ABORT` when the seat is unset.

### TDD steps

**Failing tests first** (`test_retry_resolver.py`). Use a capturing run-context helper mirrored from
`test_retry_exception_policy.py`.

**Resolver output contract (fixed here, not deferred).** A resolver's output model declares a
`disposition: ResolverDisposition` field alongside whatever state fields it writes. The compiler reads
`state["disposition"]` after the resolver node merges, coerces it to `ResolverDisposition`, and routes
on `kind`. The continue/accept state is the resolver's own merged output — the disposition holds no
state. This contract is documented in the `on_max_attempts_resolver` field docstring (Task 2). The
test state model declares it:

```python
class RS(BaseModel):
    n: int = 0
    verdict: str = "fail"
    disposition: ResolverDisposition | None = None   # resolver writes its routing signal here
    # exhaustion-metadata fields a metadata-reading resolver declares (Task 4b):
    #   root__exhaustion_reason: str = ""   (namespaced; see Task 4b)
```

A synthetic `FunctionAction[RS, RS]` resolver returns an `RS` with `disposition=ResolverDisposition(
kind=...)` and any state edits (e.g. `verdict="ok"`); the compiler reads the `disposition` field and
uses the rest of the merged `RS` as the continue/accept state.

```python
@pytest.mark.asyncio
async def test_ac1_retry_then_body_reenters_once_still_failing(...):
    """AC #1: RETRY re-executes body exactly once; the re-run still fails until(),
    so control returns to the resolver (NOT a second body run before the resolver)."""

@pytest.mark.asyncio
async def test_ac1_retry_reentry_that_passes_exits_successfully(...):
    """AC #1: a RETRY re-run whose result PASSES until() exits via the same successful
    exit as the automated pass path — it does NOT bounce back to the resolver. Assert the
    resolver node ran exactly once (one disposition consumed) and downstream sees the
    passing re-run output."""

@pytest.mark.asyncio
async def test_ac2_accept_exits_with_supplied_state(...):
    """AC #2: ACCEPT exits; downstream sees resolver-supplied state."""

@pytest.mark.asyncio
async def test_ac2_abort_terminates_without_body_reexec(...):
    """AC #2: ABORT raises RetryAborted; body does not re-execute."""
    with pytest.raises(RetryAborted):
        ...

@pytest.mark.asyncio
async def test_ac3_resolver_cycle_repeats_until_accept(...):
    """AC #3: RETRY → re-run NOT_PASSED → back to resolver → ACCEPT terminates the cycle.
    Covers the not-pass-again case: the re-run failing until() routes to the resolver,
    not to a success exit."""

@pytest.mark.asyncio
async def test_ac4_no_resolver_fails_closed_aborts(...):
    """AC #4: exhaustion with no resolver configured raises (fail-closed)."""
    with pytest.raises(RetryAborted):
        ...

@pytest.mark.asyncio
async def test_ac4_body_passes_within_attempts_behaves_as_today(...):
    """AC #4: passing body never reaches exhaustion; result identical to legacy Retry."""

@pytest.mark.asyncio
async def test_ac8_exception_in_automated_attempt_is_not_passed(...):
    """AC #8: body raise under CATCH_AND_CONTINUE counts as one NOT_PASSED attempt."""

@pytest.mark.asyncio
async def test_ac8_exception_in_retry_reentry_identical(...):
    """AC #8: body raise during a RETRY re-entry is handled by the SAME path —
    one NOT_PASSED attempt, no separate guided-exception branch. Under PROPAGATE,
    the raise propagates in both the automated and re-entry cases."""

@pytest.mark.asyncio
async def test_ac9_backstop_raises_distinct_error(...):
    """AC #9: a resolver that always RETRYs hits resolver_max_reentries and raises
    ResolverDidNotConvergeError — distinct from RetryAborted."""
    with pytest.raises(ResolverDidNotConvergeError):
        ...
    # and assert it is NOT a RetryAborted

def test_gate_resolver_pauses_then_operator_disposition_routes():
    """A GateAction resolver pauses at exhaustion (outer-graph interrupt_before + MemorySaver),
    and the operator's resumed state — carrying a `disposition` — drives the cycle. This
    exercises a real gate→disposition path, NOT merely 'it compiles'.

    Drive:
      1. invoke() with a failing body → automated phase exhausts → execution pauses BEFORE the
         gate resolver node (interrupt_before). Assert the run is interrupted (state snapshot shows
         the gate as next), proving the resolver reached the outer interrupt wiring.
      2. The operator 'sets kind' by updating state at the interrupt:
         graph.update_state(config, {"disposition": ResolverDisposition(
             kind=DispositionKind.ABORT, reason="operator declines").model_dump(),
             ... any findings written into existing state fields ...})
      3. Resume: graph.invoke(None, config). Assert RetryAborted(reason="operator declines")
         propagates — the gate's parser-set disposition routed to abort_node.

    A second variant updates with kind=ACCEPT and asserts the run exits with the operator-written
    state (no body re-exec), proving ACCEPT routes on the gate-supplied disposition.
    """
    gate = GateAction[RS, RS](interaction="stdin", prompt_key="verdict")
    r = Retry[RS, RS](max_attempts=1, until=lambda s: False,
                      body=FunctionAction[RS, RS](function=lambda s: s),
                      on_max_attempts_resolver=gate)
    graph = compile_runtime_plan(PrimitivePlan(root=r))
    config = {"configurable": {"thread_id": "gate-resolver-1"}}
    graph.invoke({"verdict": "fail"}, config=config)
    snap = graph.get_state(config)
    assert snap.next  # paused before the gate resolver node — proves outer-graph interrupt
    graph.update_state(config, {
        "disposition": ResolverDisposition(
            kind=DispositionKind.ABORT, reason="operator declines"
        ).model_dump(),
    })
    with pytest.raises(RetryAborted, match="operator declines"):
        graph.invoke(None, config=config)
```

This replaces the earlier hollow `assert graph is not None` ("compiles ≠ works") test: it forces the
gate to pause as an outer-graph node *and* asserts the operator-supplied `disposition` routes the
cycle. The §0 verification is now exercised end-to-end, not merely compiled.

For AC #8's PROPAGATE half, assert the same exception type surfaces from both an automated attempt and
a forced RETRY re-entry, demonstrating one shared code path.

**Implement:** Rework `_compile_retry` and add the cycle nodes. Import `AttemptOutcome`, the
disposition types, `RetryAborted`, `ResolverDidNotConvergeError`.

### Verification

```bash
pdm run pytest tests/agent_foundry/primitives/test_retry_resolver.py -x
pdm run pytest tests/agent_foundry/primitives/ -x          # no regressions (esp. test_retry_exception_policy)
pdm run pytest tests/agent_foundry/ -x                     # full suite
```

---

## Task 4b — Expose exhaustion metadata as state the resolver can read

**File:** `src/agent_foundry/compiler/primitive_compiler.py`
**Test file:** `tests/agent_foundry/primitives/test_retry_resolver.py`

A `Primitive` resolver reads only from **state**. The removed `on_exhaustion` callable received a rich
`RetryExhaustion` argument (reason, `attempt_failures`, `last_state`); none of that reaches a resolver
node unless `_compile_retry` writes it into declared channels **before** the resolver node runs.
Without it a resolver cannot distinguish "exhausted by clean non-pass" from "all attempts errored" —
the very input that justifies `ABORT` (def AC implied by Implementation Notes "Exhaustion metadata
into state"). This task makes that metadata available.

### What to build

Extend the §0 cycle so that on the `retry_node --(exhausted)--> resolver_node` edge, the retry node
writes exhaustion metadata into **namespaced** outer-state channels (same mechanism as the backstop
counter — `ctx.prefix`-prefixed, never a body field, threaded into the outer state schema):

```python
reason_key   = f"{ctx.prefix}__exhaustion_reason"      # RetryExhaustionReason value
failures_key = f"{ctx.prefix}__attempt_failures"       # serialized AttemptFailure list
```

- `reason_key` ← a `RetryExhaustionReason` (the existing enum, Task 1): `BODY_EXCEPTIONS` if every
  attempt raised, `CONDITION_NOT_MET` if every attempt ran without passing, `MIXED` if both occurred.
  The automated in-node loop already tracks per-attempt outcomes / `attempt_failures`; derive the
  reason from that tally at the moment of exhaustion. (`PROPAGATE` never reaches exhaustion — it
  re-raises — so only `CATCH_AND_CONTINUE` populates `BODY_EXCEPTIONS`/`MIXED`.) `BODY_EXCEPTIONS` is
  the input that justifies a resolver choosing `ABORT`.
- `failures_key` ← the accumulated `AttemptFailure` records, so a resolver can inspect what went wrong.
- These channels are written **before** the resolver node executes and persist across a gate
  interrupt/resume (declared channels, like the backstop counter). A `FunctionAction` / `AICall`
  resolver whose input model declares the same field names reads them as ordinary state.

The resolver's input model declares whichever metadata fields it consumes; the validator
field-availability rule (Task 3) already permits a resolver input that is a subset of available state,
and the metadata channels are part of that available state once widened here.

### TDD steps

**Failing tests first** (append to `test_retry_resolver.py`):

```python
@pytest.mark.asyncio
async def test_exhaustion_reason_condition_not_met_in_state(...):
    """All attempts run cleanly without passing → resolver reads CONDITION_NOT_MET."""
    # resolver is a FunctionAction whose input declares the namespaced reason field;
    # assert it observed RetryExhaustionReason.CONDITION_NOT_MET and chose accordingly.

@pytest.mark.asyncio
async def test_exhaustion_reason_body_exceptions_in_state(...):
    """Every attempt raises under CATCH_AND_CONTINUE → resolver reads BODY_EXCEPTIONS
    and (here) chooses ABORT, the disposition that input justifies."""

@pytest.mark.asyncio
async def test_attempt_failures_exposed_to_resolver(...):
    """The accumulated AttemptFailure records are readable from the namespaced
    failures channel by the resolver node."""
```

**Implement:** Write the two metadata channels in `_compile_retry` on the exhaustion transition. They
are already declared in the outer schema by the **Task 4 pre-pass** (`_collect_retry_channels` emits
`__exhaustion_reason` and `__attempt_failures` alongside `__resolver_reentries` for every Retry), so no
additional widening seam is needed here — only the writes. This is why the pre-pass emits all three
channels up front rather than the backstop counter alone.

### Verification

```bash
pdm run pytest tests/agent_foundry/primitives/test_retry_resolver.py -x -k "exhaustion or attempt_failures"
pdm run pytest tests/agent_foundry/ -x                     # full suite
```

---

## Task 5 — Synthetic end-to-end test with a non-gate resolver (AC #5, #6, #7)

**File:** `tests/agent_foundry/primitives/test_retry_resolver_e2e.py` (new)

Proves the capability is general and the resolver role is genuinely polymorphic, with **no
Archipelago dependency** and **no change to `Retry`**.

### What to build

A synthetic workflow mirroring the design-review pattern: a "designer" body produces an artifact +
automated verdict; the automated reviewer always fails; the resolver (a non-gate participant)
contributes a verdict and a disposition; on `RETRY` the body re-runs reading the resolver's verdict.

- **AC #6 / #7 (FunctionAction resolver):** resolver as a `FunctionAction[W, W]` whose output sets
  `disposition=ResolverDisposition(kind=RETRY)` once (also writing a verdict the body reads) then
  `kind=ACCEPT`. The continue/accept state is the resolver's own merged output — no nested state on the
  disposition. Assert re-entry count, final passing verdict, artifact fidelity, and clean termination.
- **AC #7 (callable-class resolver):** a `DeterministicResolver` callable class (proves polymorphism
  without any change to `Retry` or the compiler). Same assertions.
- **AC #5 (artifact / lifecycle fidelity):** install a capturing `LifecycleWriter` (as in
  `test_retry_exception_policy.py`) and assert the resolver primitive emitted the **same**
  lifecycle-event sequence as any other `FunctionAction`/`AICall` body node — i.e. the resolver
  traverses the standard state-merge + lifecycle path because it is a compiled node. Do **not** reach
  into persistence; assert structurally on emitted events. (Artifact path/payload conventions are the
  consuming product's tests, per the def.)

No `GateAction` here — the def's AC #7 is explicitly the non-gate (AICall/FunctionAction) path. (The
gate-resolver path is exercised in Task 4's `test_gate_resolver_pauses_then_operator_disposition_routes`.)

### TDD steps

Write the synthetic `WorkflowState`, designer body, and the two resolver kinds; assert via a `_run`
helper that compiles the plan and `ainvoke`s under an installed run-context. No new production code —
this task verifies Tasks 1-4. The word "human" must not appear anywhere in the file.

### Verification

```bash
pdm run pytest tests/agent_foundry/primitives/test_retry_resolver_e2e.py -v
pdm run pytest tests/agent_foundry/ -x      # full suite, no regressions
pdm lint
pdm typecheck
grep -rni "human" src/agent_foundry/primitives/retry_types.py \
  src/agent_foundry/primitives/models.py \
  src/agent_foundry/compiler/primitive_compiler.py \
  tests/agent_foundry/primitives/test_retry_resolver*.py || echo "no 'human' in new code — OK"
```

---

## Acceptance-criteria → test map

| AC | Assertion | Test |
|---|---|---|
| #1 RETRY re-enters body once; fail→resolver, pass→exit | one body re-run per RETRY; pass-on-re-run exits, fail returns to resolver | `test_ac1_retry_then_body_reenters_once_still_failing`, `test_ac1_retry_reentry_that_passes_exits_successfully` (Task 4) |
| #2 ACCEPT exits w/ state; ABORT terminates, no re-exec | downstream state; `RetryAborted` | `test_ac2_accept_exits_with_supplied_state`, `test_ac2_abort_terminates_without_body_reexec` (Task 4) |
| #3 cycle repeats until ACCEPT/ABORT/backstop | RETRY→NOT_PASSED→resolver→ACCEPT | `test_ac3_resolver_cycle_repeats_until_accept` (Task 4) |
| #4 no resolver ⇒ fail-closed ABORT; passing body unchanged | `RetryAborted`; legacy parity | `test_ac4_no_resolver_fails_closed_aborts`, `test_ac4_body_passes_within_attempts_behaves_as_today` (Task 4) |
| #5 resolver verdict same serialization / lifecycle path | capturing writer event parity | Task 5 AC #5 test |
| #6 general capability, no Archipelago dep | synthetic e2e passes | Task 5 FunctionAction-resolver test |
| #7 non-gate (function / callable-class) resolver | same re-entry/termination | Task 5 callable-class test |
| #8 exception identical in automated attempt and RETRY re-entry | NOT_PASSED both; PROPAGATE raises both | `test_ac8_exception_in_automated_attempt_is_not_passed`, `test_ac8_exception_in_retry_reentry_identical` (Task 4) |
| #9 backstop raises distinctly from ABORT | `ResolverDidNotConvergeError` ≠ `RetryAborted` | `test_ac9_backstop_raises_distinct_error` (Task 4) |

---

## Completion checklist

- [ ] `AttemptOutcome` (binary), `ResolverDisposition` (pure routing signal: `kind` + optional
      `reason`, **no state payload**), `RetryAborted`, `ResolverDidNotConvergeError` in
      `retry_types.py` — StrEnum conventions honored; tests green. `RetryExhaustion[I]` noted as an
      unused public type post-`on_exhaustion`-removal (one line; not deleted)
- [ ] `Retry` extended with `on_max_attempts_resolver` and `resolver_max_reentries` (high default);
      **no new top-level primitive**; existing fields unchanged; new types exported
- [ ] **`on_exhaustion` removed from `Retry`** — field gone, in-repo consumers updated, exported types
      adjusted; resolver seat is its sole replacement
- [ ] `_validate_retry` extended: resolver recursion + field-availability; backstop ceiling `ge=1`
      (no mutual-exclusion rule — `on_exhaustion` no longer exists)
- [ ] `_compile_retry` emits the outer-graph resolver cycle (resolver_node / body_once_node /
      abort_node), reuses the **one** body code path for automated and RETRY re-entry (AC #8); routes
      on `disposition.kind` using the resolver node's **own output state** (disposition carries no
      state); `body_once_node` evaluates `until` — PASS exits successfully, NOT_PASSED returns to the
      resolver; fail-closed by default
- [ ] State widening done by a **pre-pass** (`_collect_retry_channels`) that runs BEFORE
      `_derive_state_type` / `StateGraph` construction, folding every Retry's `ctx.prefix`-namespaced
      backstop + exhaustion-metadata channels into the outer schema. Prefix determinism guaranteed:
      compile prefixes are a pure function of tree position from root `"root"`, so the pre-pass walk
      and `_compile_retry` derive identical prefixes
- [ ] Exhaustion metadata (existing `RetryExhaustionReason` + `AttemptFailure` records, reused not
      redefined) written into namespaced state before the resolver node; a resolver reading them is
      tested (Task 4b)
- [ ] Gate resolver exercised end-to-end: pauses at exhaustion (outer-graph `interrupt_before` +
      `MemorySaver`), operator-supplied `disposition` routes the cycle (real gate→disposition path,
      not a hollow "it compiles" assertion)
- [ ] Synthetic non-gate e2e green: FunctionAction resolver + callable-class resolver (AC #6/#7) and
      lifecycle-fidelity assertion (AC #5)
- [ ] **Intentional behavior change documented:** an unset resolver now ABORTs (fail-closed),
      replacing the silent-exit default; covered by a test
- [ ] **Deferred, not implemented:** clean run-termination signal — ABORT and backstop both use the
      raise path today, as distinct exception types
- [ ] No regressions: `pdm test-unit` / `pdm test-all` pass in full
- [ ] `pdm lint` and `pdm typecheck` clean
- [ ] No new code (types, fields, docstrings, error messages, comments, tests) contains the word
      "human"
