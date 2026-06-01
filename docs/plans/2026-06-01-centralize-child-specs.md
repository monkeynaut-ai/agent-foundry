# Plan: Centralize primitive child-enumeration via `child_specs`

**Branch:** `markn/gh-62-centralize-child-specs`
**Issue:** [#62](https://github.com/730alchemy/agent-foundry/issues/62) — Refactor: centralize primitive child-enumeration (`child_specs`) to remove N-way duplication
**Goal:** Introduce a single source of truth for "what are a primitive's child primitives + their compile-prefix suffixes" so the structure is not hand-encoded independently across the validators and the compilers. Pure refactor — no behavior change.

---

## Context: base differs from the issue text

The issue body (written against `main` with the resolver-seat work) describes a **3-way** duplication: validators, compilers, and `_collect_retry_channels` (a retry-channel-widening pass), plus a `Retry.on_max_attempts_resolver` field.

**This worktree's base (post-PR #58, `6cee11d`) does not contain that work.** Verified:

- No `_collect_retry_channels` / `_state_type_with_retry_channels` anywhere in `src/` (grep: zero hits).
- `Retry` has `on_exhaustion` (`src/agent_foundry/primitives/models.py:93`), not `on_max_attempts_resolver`. No resolver / `RetryAborted` / `ABORT` code exists.
- Line numbers cited in the issue (`primitive_compiler.py:164-197`, `:393`, `:400`, `validators.py:112-281`) do not correspond to the current file.

So in this base the duplication is **2-way**: the child structure is hand-encoded in (a) each `_compile_*` in `src/agent_foundry/compiler/primitive_compiler.py` and (b) each `_validate_*` in `src/agent_foundry/primitives/validators.py`. The refactor still removes the cross-module duplication and — more importantly — establishes the abstract-method contract that makes a *future* child-enumeration consumer (the retry-channel pass, when it lands) impossible to silently desync. **This is the durable value even with only 2 current consumers.**

Decision: implement Option B (polymorphic `child_specs` on the base, abstract method) exactly as the issue's recommendation, grounded in the code that is actually here. See Open Questions for the one adjustment this base forces.

---

## Approved design (from the issue)

`child_specs(self) -> list[tuple[Primitive, str]]` on the `Primitive` base, **abstract**:

- Returns `(child, local_suffix)` pairs. The suffix is the **local** label only (`"step_0"`, `"then"`, `"body"`, `"resolver"`/`"else"`), never the full prefix — the `_` separator and `"root"` seed stay compiler concerns.
- `Primitive` becomes `BaseModel, ABC` with `@abstractmethod child_specs`. A future composite that forgets to implement it fails **loudly at instantiation** (`TypeError`), converting the silent-drop failure mode into a can't-miss error.
- The four (here: five) leaves implement `return []`: `FunctionAction`, `GateAction`, `AgentAction`, `AICall` (the issue's "AICall" leaf is present in this base).
- Consumers route through it:
  - **Validators** recurse via `[validate_primitive(c) for c, _ in prim.child_specs()]`.
  - **Compilers** derive `ctx.child(f"{ctx.prefix}_{suffix}")` from the same source, killing the write-twice prefix derivation.
- **Limitation (kept from the issue):** compilers still reference `then_branch`/`else_branch`/`body`/`on_exhaustion` directly for *role-specific edge wiring* (router→branch, body subgraph, cycle). `child_specs` only dedups the *prefix derivation* and the *validator recursion*. Cross-module duplication goes away; within-compiler role access remains.

### Suffix contract (must match current compiler prefixes exactly)

| Primitive | Children + suffix | Current compiler prefix (must preserve) |
|---|---|---|
| `Sequence` | `(step, f"step_{i}")` for each step | `f"{prefix}_step_{i}"` (`primitive_compiler.py:300`) |
| `Conditional` | `(then_branch, "then")`, `(else_branch, "else")` if not None | `f"{prefix}_then"` (`:354`), `f"{prefix}_else"` (`:359`) |
| `Loop` | `(body, "body")` | `f"{prefix}_body"` (`:421`) |
| `Retry` | `(body, "body")` | `f"{prefix}_body"` (`:474`) |
| Leaves | `[]` | n/a |

Note: in this base `Retry` has no second child (no resolver). `child_specs` returns only `(body, "body")`. The `"resolver"` suffix from the issue is **not** added here — it would be dead structure. When the resolver-seat work merges, that PR adds the `(on_max_attempts_resolver, "resolver")` pair to `Retry.child_specs` (see Open Questions).

---

## Design decisions

- **Abstract method, not concrete default-empty.** Per the issue's "lean abstract" recommendation and its documented spike (pydantic 2.13.4): the `return []` boilerplate on leaves is cheap insurance; the enforcement is the whole point of the refactor. Task 0 re-confirms the spike in this worktree's synced env before committing to it (the worktree's `.venv` currently has no deps installed).
- **Suffix is the local label only.** Returning `"then"` is a structural label; returning `f"{prefix}_then"` would bake the compiler's global naming into the data model.
- **One base, no `LeafPrimitive`/`CompositePrimitive` split.** More taxonomy than ~8 types earn (issue's stance).
- **Keep the ABC interface minimal.** Only `child_specs`. Do **not** pull `compile`/`validate` onto the base — behavior stays in the external registries (`_compiler_registry`, `_validator_registry`); the model stays inert. `child_specs` belongs on the model because "what are my children" is *structural*, not behavioral.
- **Test placeholder fix.** `tests/agent_foundry/primitives/test_primitive_models.py` uses bare `Primitive[StubInput, StubOutput]()` as a stand-in child 24 times (e.g. `:43`, `:129`). Making `Primitive` abstract breaks every one. Replace them with a concrete local leaf stub that implements `child_specs` (Task 1). This is unavoidable and load-bearing — it is the proof that the abstract base rejects bare instantiation.

---

## Task 0 — Re-confirm the ABC + Pydantic + PEP-695 spike in this env

**Why:** The issue's spike ran on `main`'s env (pydantic 2.13.4). This worktree's `.venv` has no deps installed yet. Confirm the abstract form works here before building on it.

### 0a. Sync deps

```
pdm install
```

### 0b. Spike (throwaway — do NOT commit)

Run a 5-line check confirming: (1) `class Primitive[I: BaseModel, O: BaseModel](BaseModel, ABC)` with `@abstractmethod child_specs` defines cleanly, (2) instantiating the abstract base raises `TypeError`, (3) a concrete subclass that forgets `child_specs` raises `TypeError` at instantiation, (4) a subclass implementing it instantiates and `extra="forbid"` still holds, (5) PEP-695 generic parameterization coexists.

```
pdm run python -c '
from abc import ABC, abstractmethod
from pydantic import BaseModel
class P[I: BaseModel, O: BaseModel](BaseModel, ABC):
    @abstractmethod
    def child_specs(self): ...
class SA(BaseModel): x: int
class SB(BaseModel): y: int
try:
    P[SA, SB](); print("FAIL base")
except TypeError: print("ok: base blocked")
class L[I: BaseModel, O: BaseModel](P[I, O]):
    def child_specs(self): return []
print("ok: leaf", L[SA, SB]().child_specs())
'
```

**Verify:** prints `ok: base blocked` and `ok: leaf []`. If the spike fails (metaclass conflict), STOP and record in Open Questions — fallback would be concrete default-empty + a registry-completeness test, which is strictly weaker.

---

## Task 1 — Replace bare-`Primitive` test placeholders with a concrete leaf stub

**File:** `tests/agent_foundry/primitives/test_primitive_models.py`

Done first so the suite still passes after Task 2 makes the base abstract. This is a pure test refactor; it must stay green against the *current* (non-abstract) base too.

### 1a. Add a concrete leaf stub near the top fixtures

```python
class _LeafStub(Primitive[StubInput, StubOutput]):
    """Concrete placeholder leaf for composition tests. Implements the
    structural contract so it can stand in as a child primitive."""

    def child_specs(self) -> list[tuple[Primitive, str]]:
        return []
```

(On the current non-abstract base, defining `child_specs` is harmless. After Task 2 it satisfies the abstract method.)

### 1b. Replace every `Primitive[StubInput, StubOutput]()` placeholder

Replace all 24 bare instantiations (`:43`, `:129`, `:135-137`, `:150`, `:166`, `:176`, `:186`, `:196`, `:205`, `:213`, `:234`, `:243`, `:253`, `:271-272`, `:282`, `:290`, `:305`, `:386`, `:396-397`, `:407`, …) with `_LeafStub()` — **except** the two tests that assert the base contract directly:

- `test_given_type_params_when_created_then_succeeds` (`:42`) — currently instantiates `Primitive[StubInput, StubOutput]()` to check `get_type_args`. After Task 2 this must instead use `_LeafStub()` (parameterization still flows through), OR be left to assert that the bare base raises. Decide in Task 2c.
- `test_unparameterized_primitive_raises_at_construction` (`:48`) — unaffected (still uses bare `Primitive()`, still raises for the parameterization reason).

### 1c. Verify (against current base, before Task 2)

```
pdm run pytest tests/agent_foundry/primitives/test_primitive_models.py -x -q
```

All green. No behavior change yet.

---

## Task 2 — Make `Primitive` abstract with `child_specs` + implement on every type

**Files:** `src/agent_foundry/primitives/models.py`, `src/agent_foundry/primitives/ai_call.py`

### 2a. RED — add the contract test

In `tests/agent_foundry/primitives/test_primitive_models.py`, add a `TestChildSpecs` class:

```python
def test_bare_primitive_cannot_instantiate(self):
    with pytest.raises(TypeError):
        Primitive[StubInput, StubOutput]()  # abstract child_specs

def test_subclass_forgetting_child_specs_cannot_instantiate(self):
    class Forgot(Primitive[StubInput, StubOutput]):
        pass
    with pytest.raises(TypeError):
        Forgot()

def test_sequence_child_specs_enumerates_steps(self):
    a, b = _LeafStub(), _LeafStub()
    seq = Sequence[StubInput, StubOutput](steps=[a, b])
    assert seq.child_specs() == [(a, "step_0"), (b, "step_1")]

def test_conditional_child_specs_then_only(self):
    then = _LeafStub()
    cond = Conditional[StubInput, StubOutput](condition=lambda s: True, then_branch=then)
    assert cond.child_specs() == [(then, "then")]

def test_conditional_child_specs_then_and_else(self):
    then, els = _LeafStub(), _LeafStub()
    cond = Conditional[StubInput, StubOutput](
        condition=lambda s: True, then_branch=then, else_branch=els
    )
    assert cond.child_specs() == [(then, "then"), (els, "else")]

def test_loop_child_specs(self):
    body = _LeafStub()
    loop = Loop[StubInput, StubOutput](over=lambda s: [], item_key="i", body=body)
    assert loop.child_specs() == [(body, "body")]

def test_retry_child_specs(self):
    body = _LeafStub()
    retry = Retry[StubInput, StubInput](max_attempts=1, until=lambda s: True, body=body)
    assert retry.child_specs() == [(body, "body")]

def test_leaf_child_specs_empty(self):
    fn = FunctionAction[StubInput, StubOutput](function=lambda s: StubOutput(result=""))
    assert fn.child_specs() == []
```

(Also assert `AICall`, `GateAction`, `AgentAction` return `[]` — reuse existing valid-construction fixtures from `test_primitive_models.py` / sibling test files rather than re-deriving full kwargs.)

**Verify RED:**
```
pdm run pytest tests/agent_foundry/primitives/test_primitive_models.py::TestChildSpecs -x -q
```
Fails (no `child_specs`, base not abstract).

### 2b. GREEN — base ABC + abstract method

In `src/agent_foundry/primitives/models.py`:

```python
from abc import ABC, abstractmethod
```

Change the base:

```python
class Primitive[I: BaseModel, O: BaseModel](BaseModel, ABC):
    ...  # existing docstring + _require_parameterization

    @abstractmethod
    def child_specs(self) -> list[tuple[Primitive, str]]:
        """Return this primitive's child primitives paired with their local
        compile-prefix suffix. Leaves return []. The suffix is a local label
        (``"step_0"``, ``"then"``, ``"body"``) — callers compose the full prefix."""
```

### 2c. GREEN — implement per type

`Sequence`:
```python
def child_specs(self) -> list[tuple[Primitive, str]]:
    return [(s, f"step_{i}") for i, s in enumerate(self.steps)]
```

`Conditional`:
```python
def child_specs(self) -> list[tuple[Primitive, str]]:
    specs: list[tuple[Primitive, str]] = [(self.then_branch, "then")]
    if self.else_branch is not None:
        specs.append((self.else_branch, "else"))
    return specs
```

`Loop`:
```python
def child_specs(self) -> list[tuple[Primitive, str]]:
    return [(self.body, "body")]
```

`Retry`:
```python
def child_specs(self) -> list[tuple[Primitive, str]]:
    return [(self.body, "body")]
```

`FunctionAction`, `GateAction`, `AgentAction` (in `models.py`):
```python
def child_specs(self) -> list[tuple[Primitive, str]]:
    return []
```

`AICall` (in `src/agent_foundry/primitives/ai_call.py`):
```python
def child_specs(self) -> list[tuple[Primitive, str]]:
    return []
```

Resolve the `:42` `test_given_type_params_when_created_then_succeeds` collision: switch its instantiation to `_LeafStub()` (parameterization + `get_type_args` still exercised).

### 2d. Verify GREEN

```
pdm run pytest tests/agent_foundry/primitives/test_primitive_models.py -x -q
pdm typecheck
```

Both green. `pdm typecheck` confirms the abstract-method signature and the `tuple[Primitive, str]` return type are consistent across all overrides.

---

## Task 3 — Route validators through `child_specs`

**File:** `src/agent_foundry/primitives/validators.py`

### 3a. RED — assert the recursion still happens via the shared seam

The existing recursion tests (`test_recurses_into_steps` `:201`, `test_recurses_into_body` for Loop `:225` and Retry `:293`, and the Conditional branch-recursion tests) already prove children are validated. Add **one** test that a composite with a child whose `child_specs` is honored gets its child validated — to pin the behavior to the seam:

```python
def test_validator_recurses_via_child_specs(self):
    # A Sequence whose step is itself invalid must fail — proving the
    # validator walks child_specs rather than only top-level fields.
    bad_inner = Sequence[StubInput, StubOutput](steps=[<step with output mismatch>])
    outer = Sequence[StubInput, StubOutput](steps=[bad_inner])
    with pytest.raises(TypeMismatchError):
        validate_primitive(outer)
```

(If an equivalent assertion already exists at `:201`, skip adding and rely on it — note that in the plan.) **Verify:** existing recursion tests still pass before the refactor (RED here is "no regression expected").

### 3b. GREEN — replace per-type child recursion with the shared loop

In each `_validate_*` that currently hand-recurses, replace the explicit per-child `validate_primitive(...)` calls with a single shared walk. Keep all the *type-compatibility* checks (field availability, `_types_match`) exactly as-is — those are not child-enumeration and stay per-type.

- `_validate_sequence` (`:111`): remove the `for step in seq.steps: validate_primitive(step)` loop (`:123-124`).
- `_validate_loop` (`:127`): remove `validate_primitive(loop.body)` (`:129`).
- `_validate_retry` (`:132`): remove `validate_primitive(retry.body)` (`:170`).
- `_validate_conditional` (`:173`): remove `validate_primitive(cond.else_branch)` (`:257`) and `validate_primitive(cond.then_branch)` (`:259`).

Add the shared recursion in `validate_primitive` itself (the dispatcher at `:61`), **after** the per-type validator returns:

```python
def validate_primitive(prim: Primitive) -> None:
    prim_type = type(prim)
    for cls in prim_type.__mro__:
        fn = _validator_registry.get(cls)
        if fn is not None:
            fn(prim)
            for child, _ in prim.child_specs():
                validate_primitive(child)
            return
    raise UnregisteredPrimitiveError(...)
```

**Trap to preserve:** the per-type validator must run *before* recursing into children (current order: `_validate_conditional` validates branch types, then recurses). Centralizing the recursion in the dispatcher keeps that order (validator first, then children). Confirm no validator relied on recursing *before* its own checks — none do (all recurse last).

### 3c. Verify

```
pdm run pytest tests/agent_foundry/primitives/test_primitive_validators.py -x -q
```

All green. The dispatcher now owns child recursion uniformly; per-type validators only do type-compatibility.

---

## Task 4 — Route compiler prefix derivation through `child_specs`

**File:** `src/agent_foundry/compiler/primitive_compiler.py`

The compilers still need role-specific child access for edge wiring (then vs else, body subgraph). `child_specs` replaces only the **prefix-string derivation** so the suffix is written once (on the model) instead of inline in each compiler.

### 4a. RED — pin the node-id naming via an existing-or-new assertion

Nested-primitive node ids encode the prefix scheme (`root_step_0_then`, etc.). The existing compiler/run tests in `tests/agent_foundry/primitives/test_primitive_compiler.py` and `tests/agent_foundry/compiler/test_run_primitive_plan.py` exercise nested compilation end-to-end and must stay green — they are the regression guard that the prefixes are byte-identical. No new failing test is strictly required (this is a refactor under existing coverage); add a focused assertion only if a nested node-id is not already observed by some test.

**Verify the guard exists:**
```
pdm run pytest tests/agent_foundry/primitives/test_primitive_compiler.py -q
pdm run pytest tests/agent_foundry/compiler/test_run_primitive_plan.py -q
```
Both green before the refactor.

### 4b. GREEN — `_compile_sequence`

Replace the inline `ctx.child(f"{ctx.prefix}_step_{i}")` (`:300`) by zipping `seq.child_specs()` with the steps so the suffix comes from the model:

```python
for (step, suffix) in seq.child_specs():
    entry, exit_ = _compile_node(sub_graph, step, ctx.child(f"{ctx.prefix}_{suffix}"))
    ...
```

(The `all_types` accumulation loop over `seq.steps` `:286-288` is type-collection, not child-enumeration — leave it, or optionally also drive it from `child_specs`; see Open Questions. Recommended: leave it, smaller diff.)

### 4c. GREEN — `_compile_conditional`

`then`/`else` are role-specific (router targets, merge edges), so keep the direct `cond.then_branch` / `cond.else_branch` references for wiring. Replace only the **prefix strings** `f"{ctx.prefix}_then"` (`:354`) and `f"{ctx.prefix}_else"` (`:359`) by looking up the suffix from `child_specs`. Cleanest minimal change: build a `dict(cond.child_specs())`-style lookup mapping child→suffix, or — given there are exactly two well-known roles — assert the suffixes match the model and continue using them inline. **Recommended (lowest risk):** derive `then_suffix`/`else_suffix` from `child_specs` at the top of the function, then use `ctx.child(f"{ctx.prefix}_{then_suffix}")`. This removes the duplicated literal while keeping role wiring explicit.

### 4d. GREEN — `_compile_loop` and `_compile_retry`

Both derive the body prefix from `child_specs`:

```python
((body, body_suffix),) = loop.child_specs()  # single-element for Loop
... ctx.child(f"{ctx.prefix}_{body_suffix}")
```

For `Retry`, `child_specs()` returns only `[(body, "body")]` in this base, so the same single-unpack pattern applies. **Do not** unpack assuming two elements (no resolver here).

### 4e. Verify

```
pdm run pytest tests/agent_foundry/primitives/test_primitive_compiler.py -q
pdm run pytest tests/agent_foundry/compiler/ -q
pdm typecheck
```

All green. Node ids unchanged (the regression guard from 4a proves byte-identical prefixes).

---

## Task 5 — Optional: fold the `Loop`/`Retry` body-subgraph helper

The issue's "secondary near-duplication" note: `_compile_loop` (`:413-424`) and `_compile_retry` (`:466-477`) build a near-identical body subgraph (TypedDict from `[outer_in, outer_out, body_in, body_out]` → compile body → entry/edge/END → `.compile()`).

### 5a. Extract `_compile_body_subgraph`

```python
def _compile_body_subgraph(
    outer: tuple[type[BaseModel], type[BaseModel]],
    body: Primitive,
    body_suffix: str,
    ctx: CompileContext,
) -> Any:  # compiled subgraph
    ...
```

Both call it with their respective outer I/O and `child_specs()`-derived suffix. **Keep this task last and independently revertable** — it is a nice-to-have, not load-bearing for the `child_specs` refactor. If it adds risk or obscures the diff, drop it.

### 5b. Verify

```
pdm run pytest tests/agent_foundry/primitives/test_primitive_compiler.py -q
pdm typecheck
```

---

## Task 6 — Full-suite green + lint/format

### 6a. Verify the entire unit suite (the refactor's contract: nothing changes)

```
pdm test-unit
pdm typecheck
pdm lint
pdm format
```

All green, no diffs from format. The full pre-existing suite — especially nested-`Retry`, nested-`Sequence`, and `Conditional` branch tests — must pass unchanged, since this is a behavior-preserving refactor.

### 6b. Integration (if cheap / available in this env)

```
pdm test-integration
```

Skip only if the env lacks Docker/credentials; note in the PR that integration was not run locally.

---

## Completion criteria

- [ ] `Primitive` is `BaseModel, ABC` with an `@abstractmethod child_specs`; bare and forgetful subclasses fail at instantiation (proven by test).
- [ ] All 8 primitive types implement `child_specs` returning the exact suffix contract in the table above.
- [ ] Validators recurse into children exclusively via `child_specs` (no per-type `validate_primitive(child)` calls remain).
- [ ] Compilers derive every child prefix from `child_specs` suffixes (no duplicated `f"{prefix}_<literal>"` for child node naming); role-specific wiring still references `then_branch`/`else_branch`/`body` directly.
- [ ] Node ids and all runtime behavior are byte-for-byte unchanged (full existing suite green).
- [ ] `pdm typecheck`, `pdm lint`, `pdm format` clean.

---

## Open Questions / Decisions for Review

1. **Base diverges from the issue text (2-way, not 3-way; `on_exhaustion`, no resolver).** This worktree's base (`6cee11d`, post-PR #58) predates the resolver-seat / `_collect_retry_channels` work the issue was written against. *Assumption:* implement against the code that is actually here — `Retry.child_specs` returns only `[(body, "body")]`, no `"resolver"` pair, and there is no channel-collection consumer to wire. **The abstract-method contract is still the load-bearing deliverable** — it makes the future channel-collection pass impossible to silently desync. *Decision needed:* confirm we want this landed on the pre-resolver base (it will need a trivial merge with the resolver-seat branch that adds the `(on_max_attempts_resolver, "resolver")` pair), rather than rebasing onto the newer `main` first. My recommendation: rebase the branch onto current `main` before implementing, so `child_specs` is built once with the resolver child included and the issue's full 3-way dedup is realized. If rebasing is undesirable, this plan stands as-is on the current base.

2. **Where the shared child-recursion lives for validators.** I put it in the `validate_primitive` dispatcher (runs each per-type validator, then walks `child_specs`). Alternative: have each validator call a `_recurse_children(prim)` helper. *Assumption:* dispatcher-owned recursion — it guarantees uniform "validator-first, then children" ordering and removes the recursion from every per-type function. Risk: a future validator that needs to recurse *before* its own checks couldn't (none do today). Flagging in case a per-type pre-order recursion is ever wanted.

3. **`Conditional` compiler — lookup vs. inline suffix.** Because then/else are role-specific for edge wiring, `child_specs` can't fully drive the conditional compiler. I chose to derive `then_suffix`/`else_suffix` from `child_specs` and keep role references explicit (removes the duplicated literal, keeps wiring legible). Alternative considered and rejected: a child→suffix dict lookup keyed by object identity (more machinery for two known roles).

4. **Whether `all_types` accumulation should also use `child_specs`.** `_compile_sequence`/`_compile_loop`/etc. iterate children again to collect I/O types for the subgraph TypedDict. That iteration *could* route through `child_specs` too. *Assumption:* leave it — it iterates for `get_type_args`, not for prefixes, so it's a different concern and folding it in enlarges the diff without reducing the targeted duplication. Open to folding if reviewers want a single child-iteration point.

5. **Task 5 (body-subgraph helper) inclusion.** Marked optional and last. *Assumption:* include it since the issue calls it out, but it is independently revertable if it muddies the core refactor's diff.

6. **Spike re-confirmation gate (Task 0).** The issue documents a confirmed spike on pydantic 2.13.4, but this worktree's `.venv` has no deps installed, so I could not re-run it during planning. Task 0 re-runs it post-`pdm install`. *Assumption:* the spike will pass (same pinned pydantic). If it fails, the fallback is concrete default-empty `child_specs` on the base plus a registry-completeness test enumerating all primitive types — strictly weaker (a forgetful future composite degrades to a silent leaf), so it is a fallback only.

---

## Overlap check with issue #70

**No file overlap; no risk.** Issue #70 ("Clean run-termination signal for resolver ABORT") touches the orchestration/run-termination layer: `src/agent_foundry/orchestration/runner.py` (`~204`), `summary.py`, resolver/`RetryAborted`/`ABORT` types, and (per #70's body) `container_executor.py` is *not* actually named there — #70 names `runner.py` and `summary.py`. This refactor (#62) touches only `src/agent_foundry/primitives/models.py`, `src/agent_foundry/primitives/ai_call.py`, `src/agent_foundry/primitives/validators.py`, and `src/agent_foundry/compiler/primitive_compiler.py`. Disjoint sets.

Also note: like the resolver-seat work, **#70's prerequisites are absent from this worktree's base** — there is no resolver, no `RetryAborted`, no `ABORT`, and `runner.py`'s terminal-event logic predates them. So #70 cannot even be started on this base, reinforcing that the two tracks do not collide here.
