# Plan: Centralize primitive child-enumeration via `child_specs`

**Branch:** `markn/gh-62-centralize-child-specs` (rebased onto current `main`)
**Issue:** [#62](https://github.com/monkeynaut-ai/agent-foundry/issues/62) — Refactor: centralize primitive child-enumeration (`child_specs`) to remove N-way duplication
**Goal:** Introduce a single source of truth for "what are a primitive's child primitives + their compile-prefix suffixes" so the structure is not hand-encoded independently across the validators, the compilers, and the retry-channel-collection pass. Pure refactor — no behavior change.

---

## Context: base now carries the full resolver substrate

This branch has been **rebased onto current `main`**, which carries the operator-guided-retry resolver work (PR #60 and predecessors). The duplication the issue describes is now fully present here — it is a **3-way** duplication, and the refactor targets all three sites:

1. **Compilers** — each `_compile_*` in `src/agent_foundry/compiler/primitive_compiler.py` hand-encodes child prefixes (`f"{ctx.prefix}_step_{i}"`, `f"{ctx.prefix}_then"`, `f"{ctx.prefix}_body"`, the resolver `f"{prefix}_resolver"`).
2. **Validators** — each `_validate_*` in `src/agent_foundry/primitives/validators.py` hand-recurses into children (`validate_primitive(step)`, `validate_primitive(retry.body)`, `validate_primitive(retry.on_max_attempts_resolver)`, etc.).
3. **`_collect_retry_channels`** (`primitive_compiler.py:164-199`) — a third, independent re-encoding of the *entire* child-prefix scheme, walking the plan tree to collect outer-state channels every nested `Retry` needs. Its own docstring admits the hazard: *"Prefix derivation mirrors each compiler's `ctx.child(...)` scheme exactly; diverging here means a nested Retry writes to undeclared keys that LangGraph silently drops."* This is exactly the silent-desync failure mode `child_specs` exists to kill.

The actual `Retry` model fields here (verified in `src/agent_foundry/primitives/models.py:81-108`):

- The resolver field is named **`on_max_attempts_resolver`** (`Primitive | None = None`), *not* `on_exhaustion` and *not* `on_max_attempts_resolver`'s issue-era guesses.
- `Retry` therefore has **two** children: `body` and (optionally) `on_max_attempts_resolver`.

Decision: implement Option B (polymorphic `child_specs` on the base, abstract method) exactly as the issue recommends, against the code actually here, realizing the **full 3-way dedup** including the resolver child and the channel-collection consumer.

---

## Approved design (from the issue)

`child_specs(self) -> list[tuple[Primitive, str]]` on the `Primitive` base, **abstract**:

- Returns `(child, local_suffix)` pairs. The suffix is the **local** label only (`"step_0"`, `"then"`, `"else"`, `"body"`, `"resolver"`), never the full prefix — the `_` separator and `"root"` seed stay compiler concerns.
- `Primitive` becomes `BaseModel, ABC` with `@abstractmethod child_specs`. A future composite that forgets to implement it fails **loudly at instantiation** (`TypeError`), converting the silent-drop failure mode into a can't-miss error.
- The five leaves implement `return []`: `FunctionAction`, `GateAction`, `AgentAction` (in `models.py`), and `AICall` (in `ai_call.py`).
- Consumers route through it:
  - **Validators** recurse via the shared `[validate_primitive(c) for c, _ in prim.child_specs()]` walk.
  - **Compilers** derive `ctx.child(f"{ctx.prefix}_{suffix}")` from the same source, killing the write-twice prefix derivation.
  - **`_collect_retry_channels`** recurses via `child_specs`, composing `f"{prefix}_{suffix}"` from each pair instead of re-listing the per-type prefix scheme inline.
- **Limitation (kept from the issue):** compilers still reference `then_branch`/`else_branch`/`body`/`on_max_attempts_resolver` directly for *role-specific edge wiring* (router→branch, body subgraph, resolver/abort/re-entry cycle). `child_specs` only dedups the *prefix derivation*, the *validator recursion*, and the *channel-collection recursion*. Cross-site structural duplication goes away; within-compiler role access remains.

### Suffix contract (must match current prefixes byte-for-byte)

| Primitive | Children + local suffix | Current prefix (must preserve) |
|---|---|---|
| `Sequence` | `(step, f"step_{i}")` for each step | `f"{ctx.prefix}_step_{i}"` (`primitive_compiler.py:393,400`) |
| `Conditional` | `(then_branch, "then")`, `(else_branch, "else")` if not None | `f"{ctx.prefix}_then"` (`:447,457`), `f"{ctx.prefix}_else"` (`:449,462`) |
| `Loop` | `(body, "body")` | `f"{ctx.prefix}_body"` (`:523,526`) |
| `Retry` | `(body, "body")`, then `(on_max_attempts_resolver, "resolver")` if not None | body `f"{prefix}_body"` (`:595,598`); resolver `f"{prefix}_resolver"` (`resolver_id`, `:612,766`; and `_collect_retry_channels` `:187`) |
| Leaves | `[]` | n/a |

**Retry ordering is load-bearing:** body first, resolver second. `_collect_retry_channels` walks body then resolver (`:184` then `:185-188`); the channel-collection refactor (Task 5) relies on `child_specs` yielding the same order so the merged-channel dict is byte-identical. Tests assert the exact list `[(body, "body"), (resolver, "resolver")]`.

**Resolver compile scope subtlety (do not break):** the resolver is compiled into the **outer** `graph` (not a body subgraph) via `_compile_node(graph, retry.on_max_attempts_resolver, ctx.child(resolver_id))` where `resolver_id = f"{prefix}_resolver"`. The body is compiled into its own `RetryBodyState` subgraph. `child_specs` returns both pairs regardless of which graph each is compiled into — the suffix is purely the local label; *where* it is compiled stays a `_compile_retry` concern.

---

## Design decisions

- **Abstract method, not concrete default-empty.** Per the issue's "lean abstract" recommendation and its documented spike (pydantic 2.13.4): the `return []` boilerplate on leaves is cheap insurance; the enforcement is the whole point. Task 0 re-confirms the spike in this worktree's synced env before committing to it.
- **Suffix is the local label only.** Returning `"resolver"` is a structural label; returning `f"{prefix}_resolver"` would bake the compiler's global naming into the data model.
- **One base, no `LeafPrimitive`/`CompositePrimitive` split.** More taxonomy than ~8 types earn (issue's stance).
- **Keep the ABC interface minimal.** Only `child_specs`. Do **not** pull `compile`/`validate` onto the base — behavior stays in the external registries (`_compiler_registry`, `_validator_registry`); the model stays inert. `child_specs` belongs on the model because "what are my children" is *structural*, not behavioral.
- **Test placeholder fix.** `tests/agent_foundry/primitives/test_primitive_models.py` uses bare `Primitive[StubInput, StubOutput]()` as a stand-in child 24 times. Making `Primitive` abstract breaks every one. Replace them with a concrete local leaf stub that implements `child_specs` (Task 1). This is unavoidable and load-bearing — it is the proof that the abstract base rejects bare instantiation.

---

## Task 0 — Re-confirm the ABC + Pydantic + PEP-695 spike in this env

**Why:** confirm the abstract form works in this worktree's synced env before building on it.

### 0a. Sync deps

```
pdm install
```

### 0b. Spike (throwaway — do NOT commit)

Confirm: (1) `class Primitive[I: BaseModel, O: BaseModel](BaseModel, ABC)` with `@abstractmethod child_specs` defines cleanly, (2) instantiating the abstract base raises `TypeError`, (3) a concrete subclass that forgets `child_specs` raises `TypeError` at instantiation, (4) a subclass implementing it instantiates and `extra="forbid"` still holds, (5) PEP-695 generic parameterization coexists.

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

Done first so the suite still passes after Task 2 makes the base abstract. Pure test refactor; must stay green against the *current* (non-abstract) base too.

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

Replace all 24 bare instantiations with `_LeafStub()` — **except** the two tests that assert the base contract directly:

- `test_given_type_params_when_created_then_succeeds` — currently instantiates `Primitive[StubInput, StubOutput]()` to check `get_type_args`. After Task 2 this must instead use `_LeafStub()` (parameterization still flows through). Decide the exact edit in Task 2c.
- `test_unparameterized_primitive_raises_at_construction` — unaffected (still uses bare `Primitive()`, still raises for the parameterization reason).

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

def test_retry_child_specs_body_only(self):
    body = _LeafStub()
    retry = Retry[StubInput, StubInput](max_attempts=1, until=lambda s: True, body=body)
    assert retry.child_specs() == [(body, "body")]

def test_retry_child_specs_body_and_resolver(self):
    body, resolver = _LeafStub(), _LeafStub()
    retry = Retry[StubInput, StubInput](
        max_attempts=1, until=lambda s: True, body=body,
        on_max_attempts_resolver=resolver,
    )
    # Ordering is load-bearing: body first, resolver second.
    assert retry.child_specs() == [(body, "body"), (resolver, "resolver")]

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
        (``"step_0"``, ``"then"``, ``"body"``, ``"resolver"``) — callers compose
        the full prefix."""
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

`Retry` (body first, resolver second — matches `_collect_retry_channels` and `_compile_retry` ordering):
```python
def child_specs(self) -> list[tuple[Primitive, str]]:
    specs: list[tuple[Primitive, str]] = [(self.body, "body")]
    if self.on_max_attempts_resolver is not None:
        specs.append((self.on_max_attempts_resolver, "resolver"))
    return specs
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

Resolve the `test_given_type_params_when_created_then_succeeds` collision: switch its instantiation to `_LeafStub()` (parameterization + `get_type_args` still exercised).

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

The existing recursion tests in `test_primitive_validators.py` already prove children are validated (Sequence steps, Loop/Retry body, Conditional branches, **and the Retry resolver** — `_validate_retry:192` recurses into `on_max_attempts_resolver`). Add **one** test pinning the behavior to the seam if none equivalent exists:

```python
def test_validator_recurses_via_child_specs(self):
    # A Sequence whose step is itself invalid must fail — proving the
    # validator walks child_specs rather than only top-level fields.
    bad_inner = Sequence[StubInput, StubOutput](steps=[<step with output mismatch>])
    outer = Sequence[StubInput, StubOutput](steps=[bad_inner])
    with pytest.raises(TypeMismatchError):
        validate_primitive(outer)
```

Also confirm an existing test exercises **resolver** recursion (an invalid primitive in `on_max_attempts_resolver` is validated). If not, add one — the resolver is the child the 3-way dedup specifically must not drop. **Verify:** existing recursion tests still pass before the refactor (RED here is "no regression expected").

### 3b. GREEN — replace per-type child recursion with the shared loop

In each `_validate_*` that currently hand-recurses, remove the explicit per-child `validate_primitive(...)` calls. Keep all *type-compatibility* checks (field availability, `_types_match`, the resolver-input field check at `:173-191`) exactly as-is — those are not child-enumeration and stay per-type.

- `_validate_sequence` (`:112`): remove the `for step in seq.steps: validate_primitive(step)` loop (`:124-125`).
- `_validate_loop` (`:128`): remove `validate_primitive(loop.body)` (`:130`).
- `_validate_retry` (`:133`): remove `validate_primitive(retry.body)` (`:171`) **and** `validate_primitive(retry.on_max_attempts_resolver)` (`:192`). Keep the resolver-input field-availability check (`:173-191`) — it is type-compatibility, not enumeration.
- `_validate_conditional` (`:195`): remove `validate_primitive(cond.else_branch)` (`:279`) and `validate_primitive(cond.then_branch)` (`:281`).

Add the shared recursion in the `validate_primitive` dispatcher (`:62`), **after** the per-type validator returns:

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

**Trap to preserve:** the per-type validator must run *before* recursing into children (current order: each validator does its type checks, then recurses last). Centralizing the recursion in the dispatcher keeps that order. Confirmed no validator relied on recursing *before* its own checks — all recurse last.

### 3c. Verify

```
pdm run pytest tests/agent_foundry/primitives/test_primitive_validators.py -x -q
```

All green. The dispatcher now owns child recursion uniformly (including the resolver child); per-type validators only do type-compatibility.

---

## Task 4 — Route compiler prefix derivation through `child_specs`

**File:** `src/agent_foundry/compiler/primitive_compiler.py`

The compilers still need role-specific child access for edge wiring (then vs else, body subgraph, resolver/abort/re-entry cycle). `child_specs` replaces only the **prefix-string derivation** so the suffix is written once (on the model) instead of inline in each compiler.

### 4a. RED — pin the node-id naming via existing coverage

Nested-primitive node ids encode the prefix scheme. The existing compiler/run tests in `tests/agent_foundry/primitives/test_primitive_compiler.py` and `tests/agent_foundry/compiler/test_run_primitive_plan.py` exercise nested compilation end-to-end and are the regression guard that prefixes stay byte-identical. No new failing test is strictly required (refactor under existing coverage); add a focused assertion only if a nested node-id is not already observed.

**Verify the guard exists:**
```
pdm run pytest tests/agent_foundry/primitives/test_primitive_compiler.py -q
pdm run pytest tests/agent_foundry/compiler/test_run_primitive_plan.py -q
```
Both green before the refactor.

### 4b. GREEN — `_compile_sequence`

Replace the inline `ctx.child(f"{ctx.prefix}_step_{i}")` (`:400`) and the `step_children` list build (`:393`) by zipping `seq.child_specs()` so the suffix comes from the model:

```python
specs = seq.child_specs()
step_children = [(step, f"{ctx.prefix}_{suffix}") for step, suffix in specs]
...
for (step, suffix) in specs:
    entry, exit_ = _compile_node(sub_graph, step, ctx.child(f"{ctx.prefix}_{suffix}"))
    ...
```

(The `all_types` accumulation loop over `seq.steps` `:385-387` is type-collection, not child-enumeration — leave it; see Open Questions.)

### 4c. GREEN — `_compile_conditional`

`then`/`else` are role-specific (router targets, merge edges), so keep the direct `cond.then_branch` / `cond.else_branch` references for wiring. Replace only the duplicated **prefix literals** `f"{ctx.prefix}_then"` / `f"{ctx.prefix}_else"` (at `:447,449,457,462`) by deriving the suffixes from `child_specs`. **Recommended (lowest risk):** at the top of the function build `suffix_for = {id(child): suffix for child, suffix in cond.child_specs()}`, then use `ctx.child(f"{ctx.prefix}_{suffix_for[id(cond.then_branch)]}")`. This removes the duplicated literal while keeping role wiring explicit. (Keyed by `id()` because two distinct branch primitives are guaranteed distinct objects.)

### 4d. GREEN — `_compile_loop` and `_compile_retry`

`_compile_loop` — single body child:
```python
((body, body_suffix),) = loop.child_specs()
... ctx.child(f"{ctx.prefix}_{body_suffix}")
... _state_type_with_retry_channels("LoopBodyState", fields, [(loop.body, f"{ctx.prefix}_{body_suffix}")])
```

`_compile_retry` — body is the first child; resolver is role-wired separately. Derive the **body** suffix from `child_specs` for both the body subgraph prefix (`:595,598`) and `RetryBodyState`. The resolver continues to use `resolver_id = f"{prefix}_resolver"` for its outer-graph node ids (`resolver_id`, `abort_id`, etc. at `:612-615`), since those are role-specific. To kill the duplicated `"resolver"` literal too, derive the resolver suffix from `child_specs` when present:

```python
specs = retry.child_specs()
body_suffix = specs[0][1]                       # always "body"
resolver_suffix = specs[1][1] if len(specs) > 1 else "resolver"
body_prefix = f"{prefix}_{body_suffix}"
resolver_id = f"{prefix}_{resolver_suffix}"
```

Then use `body_prefix` everywhere the body subgraph prefix was inlined, and `resolver_id` for the resolver/cycle node ids. **Do not** change the abort/re-entry/merge ids — those are this Retry's own role nodes, not children.

### 4e. Verify

```
pdm run pytest tests/agent_foundry/primitives/test_primitive_compiler.py -q
pdm run pytest tests/agent_foundry/compiler/ -q
pdm typecheck
```

All green. Node ids unchanged (the regression guard from 4a proves byte-identical prefixes).

---

## Task 5 — Route `_collect_retry_channels` through `child_specs` (the third dedup site)

**File:** `src/agent_foundry/compiler/primitive_compiler.py`

`_collect_retry_channels` (`:164-199`) currently re-encodes the *entire* child-prefix scheme inline (Sequence steps, Conditional then/else, Loop body, Retry body+resolver). This is the third independent copy of the structure — and the most dangerous one, because a divergence silently drops state keys. Replace its hand-rolled per-type recursion with a single walk over `child_specs`.

### 5a. RED — pin nested-Retry channel collection

The existing tests proving nested-Retry channels are declared are the regression guard — specifically the test added in `dae6497` ("inject Retry channels into nested subgraphs"). Confirm coverage exists for: a Retry nested inside a Sequence step, inside a Loop/Retry body, and a Retry **whose resolver subtree itself contains a Retry** (resolver-branch recursion via the `f"{prefix}_resolver"` path). If the resolver-nested-Retry case is not covered, add a focused compile-time test asserting the resolver-subtree retry's `f"{prefix}_resolver_..."` channels appear in the owning graph's schema — this is the path the inline code special-cased (`:185-188`) and the one most likely to silently regress.

**Verify guard:**
```
pdm run pytest tests/agent_foundry/compiler/ -q
```
Green before the refactor.

### 5b. GREEN — drive recursion from `child_specs`

Replace the `isinstance` chain (`:181-197`) with: collect this node's own channels if it is a `Retry`, then recurse over `child_specs`, composing each child's full prefix from the local suffix.

```python
def _collect_retry_channels(prim: Primitive, prefix: str) -> dict[str, Any]:
    channels: dict[str, Any] = {}
    if isinstance(prim, Retry):
        channels.update(_retry_channels(prefix))
        channels.update(WELL_KNOWN_METADATA_CHANNELS)
    for child, suffix in prim.child_specs():
        channels.update(_collect_retry_channels(child, f"{prefix}_{suffix}"))
    return channels
```

This preserves the exact prefixes: `child_specs` yields `("body")`, `("step_{i}")`, `("then"/"else")`, and (for Retry) `("body")` then `("resolver")` — composed into `f"{prefix}_body"`, `f"{prefix}_step_{i}"`, `f"{prefix}_then"`/`f"{prefix}_else"`, `f"{prefix}_resolver"`, identical to the inline code. The `Retry`-only `_retry_channels` + `WELL_KNOWN_METADATA_CHANNELS` injection stays gated on `isinstance(prim, Retry)`; only the *child enumeration* moves to `child_specs`.

Note: this also fixes a latent gap — the inline version had **no `AICall` / leaf branch** (leaves fall through to `return channels`), and no general fallthrough for unknown composite types. The `child_specs` walk handles every primitive uniformly (leaves return `[]`), so a future composite cannot silently skip channel collection.

### 5c. Verify

```
pdm run pytest tests/agent_foundry/compiler/ -q
pdm typecheck
```

All green. The channel-collection prefix scheme is now derived from the same `child_specs` source as the compilers and validators.

---

## Task 6 — Optional: fold the `Loop`/`Retry` body-subgraph helper

The issue's "secondary near-duplication": `_compile_loop` and `_compile_retry` build a near-identical body subgraph (TypedDict from outer/body I/O → compile body → entry/edge/END → `.compile()`).

### 6a. Extract `_compile_body_subgraph`

```python
def _compile_body_subgraph(
    outer: tuple[type[BaseModel], type[BaseModel]],
    body: Primitive,
    body_prefix: str,
    ctx: CompileContext,
) -> Any:  # compiled subgraph
    ...
```

Both call it with their respective outer I/O and `child_specs()`-derived body prefix. **Keep this task last and independently revertable** — nice-to-have, not load-bearing. Drop it if it obscures the diff.

### 6b. Verify

```
pdm run pytest tests/agent_foundry/primitives/test_primitive_compiler.py -q
pdm typecheck
```

---

## Task 7 — Full-suite green + lint/format

### 7a. Verify the entire unit suite (the refactor's contract: nothing changes)

```
pdm test-unit
pdm typecheck
pdm lint
pdm format
```

All green, no diffs from format. The full pre-existing suite — especially nested-`Retry`, the resolver-cycle tests, nested-`Sequence`, and `Conditional` branch tests — must pass unchanged, since this is a behavior-preserving refactor.

### 7b. Integration (if cheap / available in this env)

```
pdm test-integration
```

Skip only if the env lacks Docker/credentials; note in the PR that integration was not run locally.

---

## Completion criteria

- [ ] `Primitive` is `BaseModel, ABC` with an `@abstractmethod child_specs`; bare and forgetful subclasses fail at instantiation (proven by test).
- [ ] All 8 primitive types implement `child_specs` returning the exact suffix contract in the table above; `Retry` returns `[(body, "body")]` or `[(body, "body"), (resolver, "resolver")]`.
- [ ] Validators recurse into children exclusively via `child_specs` (no per-type `validate_primitive(child)` calls remain — including the resolver child).
- [ ] Compilers derive every child prefix from `child_specs` suffixes (no duplicated `f"{prefix}_<literal>"` for child node naming); role-specific wiring still references `then_branch`/`else_branch`/`body`/`on_max_attempts_resolver` directly.
- [ ] `_collect_retry_channels` recurses via `child_specs` (no inline `isinstance` per-type prefix scheme remains).
- [ ] Node ids, retry channels, and all runtime behavior are byte-for-byte unchanged (full existing suite green).
- [ ] `pdm typecheck`, `pdm lint`, `pdm format` clean.

---

## Open Questions / Decisions for Review

1. **Conditional compiler — `id()`-keyed suffix lookup vs. inline.** then/else are role-specific for edge wiring, so `child_specs` can't fully drive the conditional compiler. I chose to build an `{id(child): suffix}` map from `child_specs` and keep role references explicit (removes the duplicated literal, keeps wiring legible). Alternative considered and rejected: keep the two literals inline and add a unit assertion that they equal the `child_specs` suffixes. *Recommendation:* the `id()` map. Flag if reviewers prefer the lighter inline-plus-assert.

2. **Where the shared child-recursion lives for validators.** I put it in the `validate_primitive` dispatcher (runs each per-type validator, then walks `child_specs`). Alternative: a `_recurse_children(prim)` helper called by each validator. *Assumption:* dispatcher-owned recursion — uniform "validator-first, then children" ordering, removes recursion from every per-type function. Risk: a future validator needing pre-order child recursion couldn't (none do today).

3. **`all_types` accumulation still iterates children directly.** `_compile_sequence`/`_compile_loop`/`_compile_conditional` iterate children a second time to collect I/O types for the subgraph TypedDict (via `get_type_args`). That iteration *could* also route through `child_specs`. *Assumption:* leave it — it iterates for types, not prefixes; folding it in enlarges the diff without reducing the targeted duplication. Open to folding if reviewers want a single child-iteration point.

4. **`_collect_retry_channels` leaf/unknown-type behavior changes (intentionally).** The inline version silently returned `{}` for any primitive not in its `isinstance` chain (including `AICall` and any future composite). The `child_specs` walk instead recurses uniformly. For current leaves this is identical (they return `[]`). The behavioral *improvement* is that a future composite with retry-bearing children can no longer be silently skipped. Confirm this is desired (it is the whole point of the refactor) — no current test should change.

5. **Task 6 (body-subgraph helper) inclusion.** Marked optional and last. *Assumption:* include it since the issue calls it out, but it is independently revertable if it muddies the core refactor's diff.

6. **Spike re-confirmation gate (Task 0).** This worktree's `.venv` was still syncing during planning, so the spike could not be re-run. Task 0 re-runs it post-`pdm install`. *Assumption:* the spike passes (same pinned pydantic 2.13.4 as `main`). If it fails, the fallback is concrete default-empty `child_specs` + a registry-completeness test — strictly weaker (a forgetful future composite degrades to a silent leaf), a fallback only.

*(Resolved — formerly Open Question #1: branch base.* The branch is now rebased onto current `main`, which carries the full resolver substrate. The reduced 2-way scope is obsolete; this plan covers the full 3-way dedup — compilers, validators, and `_collect_retry_channels` — with the `(on_max_attempts_resolver, "resolver")` child included.)*

---

## Overlap check with issue #70

**No file overlap; no risk.** Issue #70 ("Clean run-termination signal for resolver ABORT") is a run-outcome/termination-classification change living entirely in the orchestration layer: `src/agent_foundry/orchestration/runner.py` (`~204`, where a caught `RetryAborted` currently becomes `RUN_FAILED`) and `summary.py`. Its envelope/terminal-outcome work does **not** touch `src/agent_foundry/primitives/` or the child-enumeration regions of `primitive_compiler.py` (`child_specs` derivation, `_collect_retry_channels`, per-type `_compile_*` prefix strings).

This refactor (#62) touches only:
- `src/agent_foundry/primitives/models.py`
- `src/agent_foundry/primitives/ai_call.py`
- `src/agent_foundry/primitives/validators.py`
- `src/agent_foundry/compiler/primitive_compiler.py` (child-enumeration regions only)

Disjoint from #70's `orchestration/runner.py` + `summary.py`. The two tracks share the `Retry`/resolver *concepts* but edit non-overlapping files; #62 can land independently of #70.
