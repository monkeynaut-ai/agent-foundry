---
feature_slug: operator-guided-retry
created_at: 2026-05-24
revised_at: 2026-05-30
---

# Operator-Guided Retry (Resolver Seat on `Retry`)

> **Revision note (2026-05-30).** An earlier version of this def framed the capability as a new
> `GuidedRetry` composite primitive. Design review of that approach found it (a) duplicated
> `Retry`'s loop semantics, (b) silently dropped two of its own acceptance criteria (artifact
> fidelity and exception-policy interaction), and (c) could not actually host a blocking operator
> gate under the current compiler. The capability is now expressed as a **backwards-compatible
> extension of `Retry`**: a single *resolver seat* consulted when the automated loop exhausts. See
> `archipelago/docs/architecture-wins.md` for the design principles that drove the reframe.

## Problem Statement

Agent Foundry's `Retry` primitive lets an automated reviewer judge whether a body's output is
acceptable and re-run the body up to `max_attempts`. When attempts exhaust, the parent reads the
state and routes accordingly — typically aborting the working session. The operator's only options
are to rubber-stamp a flawed output or discard an hour of agent work and start over.

This is too coarse for high-value, long-running workflows like Archipelago's design pipeline. The
operator often has the diagnostic insight the automated reviewer lacked — they can see exactly what
the agent is getting wrong and could correct it with a single round of feedback. But there is no
path to feed that feedback back to the body and re-enter the retry cycle.

## Feature Intent

Extend `Retry` so that, when the automated loop exhausts without passing, an external participant
can intervene, contribute feedback shaped like a reviewer's verdict, and have the loop re-enter the
body with that feedback in place of the automated verdict — repeatable until the participant decides
to accept or terminate.

"Operator" names a **role, not a species**: the role can be filled by a human at a terminal, by
another agent reasoning about the failed verdicts, or by a programmatic process (a deterministic
rule engine). The framework must remain agnostic to which kind of participant fills the role.
Differences in interaction mechanism (stdin vs. an agent invocation vs. a function call) are the
consuming product's concern.

The capability sits at the primitive layer — as an extension of `Retry`, not a specialized feature
on `GateAction` — because the bookkeeping the operator participates in (here are the prior verdicts,
here is the artifact, here is my feedback) is the same bookkeeping the automated reviewer
participates in. The framework treats the operator as another source of the same verdict shape.

## The Resolver Seat (design summary)

`Retry` gains **one** seat — an `on_max_attempts_resolver: Primitive | None` field — consulted when
the automated loop exhausts `max_attempts` without `until` passing. This is the *sole* exhaustion
mechanism: it **replaces** the existing `on_exhaustion` callable hook, which is removed, not kept
alongside. There is exactly one place that answers "what to do when attempts are spent," and what
goes in it is always a `Primitive`.

A bare callable is deliberately **not** accepted: `FunctionAction` already *is* "a callable in the
seat" — a thin wrapper the framework treats uniformly (validation, lifecycle events, node identity).
Accepting a raw callable too would add a parallel compiler/validator path for zero new capability. A
consumer wanting a light, non-blocking resolver passes a `FunctionAction`; the light/heavy split is
in-node-loop vs. graph-cycle (decided by whether the occupant can interrupt), not callable-vs-wrapper.

The seated primitive (a `FunctionAction`, `AICall`, or `GateAction`) returns a **disposition** that
drives what happens next. Three concerns that were previously tangled are now separated onto distinct
axes:

- **Attempt outcome** (per attempt) is binary: `PASSED | NOT_PASSED`. One axis — did this attempt
  pass `until`?
- **`exception_policy`** (static config; the existing `RetryExceptionPolicy` enum, reused as-is)
  maps a body exception to an outcome: `PROPAGATE` (re-raise; loop dies — for genuine bugs / infra
  failures) or `CATCH_AND_CONTINUE` (the raise becomes a `NOT_PASSED` attempt: consumed, state
  restored, loop continues). The policy is
  deliberately blunt — a *selective* exception taxonomy (transient vs. auth) belongs one layer down,
  in the body/executor, not in `Retry`.
- **Disposition** (resolver → `Retry`, at exhaustion) is a discriminated union:
  - `ACCEPT{state}` — take the supplied state; the run proceeds downstream.
  - `ABORT{reason}` — terminate the run.
  - `RETRY{state}` — re-enter the body **once** with the supplied state, then return to the resolver.

The disposition is the resolver primitive's **output contract**: `Retry` owns the type; the seated
primitive populates it (a `GateAction` translates raw operator input into a disposition; an `AICall`
resolver's structured output *is* the disposition).

**Default (fail-closed).** When the seat is unset, exhaustion-without-pass yields `ABORT`, not a
silent pass-through. Absence of a decision is itself a decision to stop — flawed output must not flow
downstream unexamined. (This reverses plain `Retry`'s prior silent-exit default; pass-through is now
opt-in via a resolver that returns `ACCEPT`.)

**`max_attempts` is unchanged.** It bounds the automated phase only and is never refreshed. After
exhaustion it stops being the gate; each `RETRY` grants exactly one body re-run, then control returns
to the resolver. There is no second budget counter.

**Runaway protection.** The `RETRY` budget is operator-governed (a human self-bounds by eventually
choosing `ACCEPT`/`ABORT`). Because the same seat can hold a *non-human* resolver that could loop
forever, `Retry` carries a separate **safety backstop**: a high-default ceiling on consecutive
`RETRY` re-entries that, when tripped, **raises** ("resolver did not converge"). This is a safety
invariant, not a budget — it must not be named or modeled as a knob the resolver reasons about, and
its trip is an *error* path, distinct from an intentional `ABORT`.

## Desired Outcomes

### User Outcomes

- An operator presented with a failed design review can provide their own findings and have the
  body attempt one more revision, repeatable as needed, without restarting the working session.
- Operator contributions are captured in run artifacts with the same structural fidelity as
  automated reviewer verdicts, so the post-run record is uniform.

### Business Outcomes

- Working sessions that would otherwise be discarded after retry exhaustion can be salvaged with
  external judgment, reducing wasted agent work and cycle time on high-cost workflows.
- `Retry` gains a reusable, participant-agnostic pattern for external verification applicable to any
  retry-based workflow.

## Scope Boundaries

- Out of scope: any change to `Retry` behavior **when no resolver is configured beyond the new
  fail-closed default** (see Constraints — the default change is deliberate, not incidental).
- Out of scope: a specific UX for collecting the operator's input. Whether the operator types JSON
  at a terminal, fills a web form, or uses a richer future mechanism is a product concern.
- Out of scope: the structure of the operator's verdict payload. The consuming product defines its
  own verdict Pydantic model; the framework treats it as opaque state.
- Out of scope: the comm channel / transport behind a gate resolver (stdin vs. Slack). That is a
  property of the seated primitive and its transport binding, not of `Retry`.
- Out of scope: durability of operator interventions across process restarts beyond what the
  existing `GateAction` interrupt/checkpoint substrate already provides.
- Out of scope: simultaneous interventions by multiple operators. Single-operator, single-resolver
  is the contract.
- Out of scope (deferred to a separate spec): a **clean run-termination runtime signal**. `ABORT`
  terminates today via the exception/raise path (the mechanism the runaway backstop and Archipelago's
  current exhaustion handler already use). A future runtime signal will let `ABORT` terminate *cleanly*
  — as a non-error terminal outcome distinguishable from a crash — but that is a quality upgrade, not
  a prerequisite for this feature.

## Assumptions

- Consuming workflows are expressed using the existing `Primitive[I: BaseModel, O: BaseModel]`
  composition model.
- Gate resolvers interact via the existing `GateAction` interrupt/checkpoint substrate.
- The runtime needs no new concept of participant kinds — the resolver is a participant whose output
  (a disposition) appears in state, no different from any other primitive's output.

## Dependencies

- Existing `Retry` primitive and its compiler.
- Existing `GateAction` primitive and its compiler (interrupt-before + top-level checkpointer).
- Existing `Conditional` primitive (for routing the disposition).
- Existing `Retry.exception_policy` capability (already landed) — folded into the binary-outcome
  model above.
- Pydantic-based flat state passing used uniformly by all primitives today.

## Constraints

- Must be a **backwards-compatible extension of `Retry`** — no new primitive, and no new
  runtime-level hooks tied to any specific participant kind.
- The one intentional behavior change is the **fail-closed default** (unset seat ⇒ `ABORT` on
  exhaustion, replacing silent state pass-through). Consumers relying on the old silent-exit must opt
  in to pass-through with a resolver that returns `ACCEPT`. This is deliberate and must be documented,
  not hidden.
- The capability must be **general and participant-agnostic**. No type name, field name, docstring,
  error message, or comment in the new code may contain the word "human". No Archipelago-specific
  naming (no `DesignReviewGate`, no `OperatorGuidedDesigner`). (Pre-existing "human" usage in
  unrelated code is out of scope.)
- Operator-provided verdicts must be captured with the same fidelity as automated verdicts. This is
  satisfied **structurally**: the resolver is a `Primitive` compiled as a graph node, so its output
  traverses the same state-merge and lifecycle-event path as any body primitive. `Retry` must **not**
  reach into persistence to assert fidelity — doing so would be a layering violation. Artifact path
  and payload conventions are the consuming product's concern.
- New fields must follow the framework's `Primitive[I, O]` parameterization rules.
- The exception/outcome model must be **single-axis**: a body exception under `CATCH_AND_CONTINUE`
  is simply a `NOT_PASSED` attempt, counted against the one attempt budget exactly as a clean
  non-passing attempt is. There must be no separate "exception during a guided iteration" code path —
  a `RETRY` re-enters the same body, so an exception there is handled identically. No cross-product of
  (exception × phase) may exist for a consumer to stumble into.

## Acceptance Criteria

1. **Given** a `Retry` whose body produces an automated verdict and whose resolver is configured,
   **when** the loop exhausts without passing and the resolver returns `RETRY{state}`, **then** the
   body re-executes exactly once with the resolver-supplied state substituted for the automated
   verdict, after which control returns to the resolver.
2. **Given** the same `Retry`, **when** the resolver returns `ACCEPT{state}`, **then** the loop exits
   and the run proceeds downstream with that state; **when** it returns `ABORT{reason}`, **then** the
   run terminates and the body does not re-execute.
3. **Given** the resolver returns `RETRY` and the post-re-entry attempt again produces a `NOT_PASSED`
   outcome, **when** control returns to the resolver, **then** the resolver may again choose
   `ACCEPT` / `ABORT` / `RETRY`. The cycle continues until `ACCEPT`/`ABORT`, or until the safety
   backstop trips.
4. **Given** a `Retry` with **no resolver configured** (`on_max_attempts_resolver` unset), **when**
   the loop exhausts without passing, **then** the run aborts (fail-closed default) rather than
   silently passing state downstream. A `Retry` whose body passes within `max_attempts` behaves
   exactly as today. (The prior `on_exhaustion` callable is removed; its old "return state" and
   "raise" behaviors map onto a `FunctionAction` resolver returning `ACCEPT` or `ABORT`.)
5. **Given** a completed run containing one or more resolver-supplied verdicts, **when** the run's
   artifacts are inspected, **then** each resolver verdict appears with the same serialization and
   lifecycle-event sequence as any other primitive's output — because the resolver is a primitive on
   the same state/event path. (Artifact path/payload conventions are asserted by the consuming
   product's tests, not the framework's.)
6. **Given** the resolver seat is exercised by a synthetic test workflow with no Archipelago
   dependency, **when** it runs end-to-end, **then** all assertions about re-entry and termination
   hold — proving the capability is general.
7. **Given** a synthetic workflow where the resolver is a non-human participant (an `AICall` or a
   `FunctionAction`, not a gate), **when** it runs end-to-end producing `ACCEPT`/`ABORT`/`RETRY`,
   **then** the same re-entry and termination assertions hold with no change to `Retry` — proving the
   resolver role is genuinely polymorphic across participant kinds.
8. **Given** a `Retry` with `exception_policy = CATCH_AND_CONTINUE` and a configured resolver,
   **when** the body raises during an automated attempt, **and again when** it raises during a
   `RETRY` re-entry, **then** in both cases the exception is recorded and treated as a `NOT_PASSED`
   attempt counted against the single attempt budget — identically — with no separate
   guided-iteration exception path. With `exception_policy = PROPAGATE`, the exception re-raises and
   the loop terminates in both cases.
9. **Given** a resolver that returns `RETRY` unconditionally (e.g. a misconfigured non-human
   participant), **when** consecutive re-entries reach the safety backstop ceiling, **then** the
   `Retry` raises a distinct "resolver did not converge" error — separate from an intentional `ABORT`
   — rather than looping unbounded.

## Implementation Notes (non-normative)

These record findings from the compiler review so the implementation plan starts from solid ground;
they are not part of the contract.

- **Re-entry must be graph topology, not a Python loop.** `Retry` today compiles to a single graph
  node whose Python loop invokes the body as an isolated sub-graph. A `GateAction` only interrupts as
  an *outer-graph* node (its id is collected into the top-level `interrupt_before` list). A gate
  invoked inside the retry node's Python loop cannot interrupt/resume correctly — resume re-runs the
  node from the top and wipes loop-carried locals. The post-exhaustion phase must therefore be wired
  as a cycle of real outer-graph nodes:
  `retry_node --exhausted--> resolver_node --RETRY--> body_once_node --> resolver_node`, with
  `ACCEPT`→downstream and `ABORT`→terminate. The automated phase may remain an in-node loop (its body
  has no gate and never interrupts).
- **State widening.** Fields the cycle must carry across the gate interrupt must be channels in the
  outer state schema (LangGraph persists only declared channels). For Archipelago this is already
  true — the root state declares all verdict fields flat. The only new state is the backstop counter;
  namespace it with the node's unique compile prefix to avoid collisions between sibling resolver
  loops.
- **General-case field collisions.** Two sibling resolver loops whose bodies use *private* same-named
  fields would alias once lifted to shared flat state. This is not triggered by design review; defer
  the scope-translation machinery (mapping namespaced outer keys ↔ bare body field names at the
  `_scope_in`/`_scope_out` boundary) until a plan actually needs it.
- **Exhaustion metadata into state.** The removed `on_exhaustion` callable received a rich
  `RetryExhaustion` argument (reason, `attempt_failures`, `last_state`). A `Primitive` resolver reads
  from **state**, so the equivalent metadata must be written into state channels before the resolver
  node runs — otherwise a resolver cannot, e.g., distinguish "exhausted by clean non-pass" from "all
  attempts errored" (the input that justifies an `ABORT`). Treat "expose exhaustion metadata as state
  the resolver can read" as an explicit implementation task, and namespace those channels like the
  backstop counter.

## References

- `agent-foundry/docs/plans/retry-resolver-seat.md` — the implementation plan for this revision.
- `archipelago/docs/architecture-wins.md` — design principles behind the reframe.
- `archipelago/docs/archive/2026-05-24-design-review-design.md` — the design-review v1 that defers
  the operator `GUIDE` action to this platform work.
- `agent_foundry/primitives/models.py` — `Retry`, `GateAction`, `Conditional`, `FunctionAction`.
- `agent_foundry/primitives/retry_types.py` — `RetryExceptionPolicy`, `RetryExhaustion`,
  `AttemptFailure`.
- `agent_foundry/compiler/primitive_compiler.py` — `_compile_retry`, `_compile_gate_action`,
  `compile_runtime_plan` (the in-node-loop vs. outer-graph-node distinction documented above).
