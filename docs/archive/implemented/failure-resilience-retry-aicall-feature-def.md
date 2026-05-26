---
feature_slug: failure-resilience-retry-aicall
created_at: 2026-05-24
---

# Failure Resilience: Retry Body Exceptions and AICall Executor

This document defines two complementary capabilities to be implemented concurrently, plus the interaction model that governs how they compose. They are bundled here because their value is greatest when delivered together — a workflow that combines both gains both wide-net body-failure tolerance (via `Retry`) and per-primitive customization power (via `AICall`) — but each capability has its own scope, constraints, and acceptance criteria so that "done" remains independently verifiable.

## Problem Statement

Agent Foundry workflows currently cannot survive transient failures in the work they orchestrate. Two specific gaps drive this:

1. **`Retry` does not catch body exceptions.** When the body of a `Retry` raises, the exception propagates immediately through the surrounding `Sequence` and unwinds the entire compiled graph, forfeiting the remaining attempts that `max_attempts` ostensibly permits. There is no way for a consumer to opt into "treat the exception as a failed attempt and try again." This matters most when the body contains fallible operations whose failures are transient and survivable — an `AICall` hitting a provider 5xx, an `AgentAction` whose container exits non-zero on a flake, a `FunctionAction` calling a temporarily-unreachable external service.
2. **`AICall` does not allow the consumer to customize its inference call.** Today the compiler hard-codes `invoke_ai_call(action, model_input)`, with no hook for the consumer to interpose. This blocks not only consumer-side exception handling and fallback-verdict synthesis but also a broad set of valuable customizations — mocking inference for tests, wrapping calls with metrics or tracing, swapping inference backends per primitive, fault injection at the primitive layer, content-addressed caching of inference outputs.

The cost of either gap grows with how much upstream work the failure occurs inside of. A single transient AICall failure inside a deeply-embedded `Retry` can discard tens of minutes of completed agent work; the inability to mock that AICall for tests means full-workflow tests must hit real providers, which is too expensive and too flaky for continuous integration.

## Feature Intent

Address both gaps in one coordinated effort:

- **Capability A — Retry body-exception policy.** Allow `Retry` consumers to declare, per-primitive, what behavior the framework should apply when the body raises. The current "propagate" behavior remains the default and is unchanged for every existing consumer. A new opt-in policy lets consumers say "treat a body exception as a failed attempt and continue to the next one." This is a wide-net solution: it applies to any fallible body — `AICall`, `AgentAction`, `FunctionAction`, `Sequence` — without requiring per-body code changes.
- **Capability B — Configurable AICall executor.** Add an `executor` field to `AICall` that mirrors the pattern `AgentAction` already follows: a default executor (`invoke_ai_call`) handles the common case, but consumers may pass any callable matching the executor contract to interpose their own behavior. Exception handling is one use case among many — mocking, observability wrapping, alternative backends, caching, fault injection — that this hook enables.

Both capabilities sit on existing primitives rather than introducing new ones. Each capability's semantic fits squarely within what its primitive already promises: `Retry` already encodes "this body might not succeed on the first try" via `max_attempts`, and the new policy generalizes what counts as a non-success; `AgentAction` already exposes `executor` as a consumer-configurable callable, and `AICall` gains the same shape.

## Desired Outcomes

### User Outcomes

- A consumer wrapping a fallible body in `Retry` can opt into treating transient body exceptions as consumed attempts rather than fatal errors, without writing any try/except code themselves.
- A consumer of `AICall` can interpose their own callable in place of the default inference call — to mock for tests, to wrap with metrics or tracing, to synthesize fallback verdicts on exception, to swap inference backends, to cache, or to inject faults — without forking or subclassing the primitive.
- When `Retry` exhausts attempts under the opt-in policy with the body raising every time, the consumer receives a clear, structured failure signal — not a silent state-unchanged exit — so the parent control flow can route the same way it would for a non-passing automated verdict.

### Business Outcomes

- Agent Foundry workflows become operationally robust to transient infrastructure errors without each workflow re-inventing exception-handling code.
- The cost of a single transient failure scales with the failure itself, not with the depth of work upstream of it, making large multi-stage workflows viable in production environments where provider reliability is below 100%.
- Full-workflow tests become tractable: an `AICall` mock executor lets workflow tests run deterministically and cheaply without invoking live LLM providers, dramatically reducing CI cost and flakiness for downstream products like Archipelago.

## Scope Boundaries

- Out of scope: equivalent exception policies on other control-flow primitives (`Sequence`, `Loop`). Each has different semantics around in-progress state and would warrant its own feature definition.
- Out of scope: distinguishing exception kinds in the `Retry` policy (transient vs. permanent, provider-specific error codes). The policy is binary — either the consumer opts into treating-as-failure or they don't. Consumers that need richer routing wrap their body in a `FunctionAction` (or, for AICalls, a custom executor) that converts specific exception types into non-exceptional return values.
- Out of scope: automatic backoff or delay between `Retry` attempts. Current `Retry` runs attempts back-to-back; this work preserves that.
- Out of scope: a framework-provided "default exception-tolerant executor" for `AICall`. The executor field is a hook — what the consumer passes is their concern; the framework supplies only the default `invoke_ai_call`.
- Out of scope: changes to `AgentAction.executor` or to the executor contract for any other primitive. This work introduces the `executor` field on `AICall` only.

## Assumptions

- Consumers will be expressed as Pydantic-typed primitives composed using the existing `Primitive[I: BaseModel, O: BaseModel]` model.
- For `Retry` Capability A: state mutations from a failed attempt should be discarded — the next attempt should see state as it was before the failed attempt began.
- For `AICall` Capability B: the executor's return value must be an instance of the AICall's output type `O`. The framework's existing state-update validation enforces this; the executor is not exempt from output typing.
- Observability infrastructure (lifecycle events, artifact capture) is in place and will be extended as needed to record exception events under the new `Retry` policy.

## Dependencies

- Existing `Retry` primitive and its compiler in `agent_foundry.primitives.models` and `agent_foundry.compiler.primitive_compiler`.
- Existing `AICall` primitive (same modules) and the `invoke_ai_call` callable in `agent_foundry.ai_models.execute.invoke`.
- Existing `AgentAction` primitive — used as the precedent shape for the new `AICall.executor` field; no changes to `AgentAction` itself.
- Existing primitive validator registry.
- Existing lifecycle-event infrastructure (`agent_foundry.orchestration.lifecycle_events`).

---

## Capability A — Retry Body-Exception Policy

### Capability-Specific Intent

Add a configuration field on `Retry` that selects what happens when the body raises. Default value preserves today's behavior (propagate). The opt-in value treats the exception as a failed attempt, restores state to its pre-attempt snapshot, and proceeds to the next attempt as if the body had returned normally with an unmet `until` condition.

When all attempts under the opt-in policy raise and `max_attempts` is exhausted, `Retry` must surface a clear, structured failure signal to the parent — not silently exit with state unchanged. The exact signal shape is for the implementer to choose, but it must allow the parent's `Conditional` to route to a `GateAction` the same way it would for a non-passing automated verdict.

### Capability-Specific Constraints

- The new field must be a `StrEnum`-typed configuration field on `Retry`, not a callable or arbitrary type, so policy values are first-class symbols that LSP can navigate (per the framework's data-model conventions in CLAUDE.md).
- The default value of the new field must be the existing behavior (propagate). No existing `Retry` consumer may need to change code.
- Exception details (type, message, attempt number, optional stack trace) must be captured in run artifacts when the opt-in policy is in effect, so post-run analysis can distinguish "body raised and was tolerated" from "body returned normally and the until-condition was false."
- The implementation must not require changes to bodies — any existing fallible primitive used as a `Retry.body` becomes resilient by changing the `Retry` configuration only, with no edits to the body or its underlying primitive.

### Capability-Specific Acceptance Criteria

A1. **Given** a `Retry` configured with the default exception policy and a body that raises on the first attempt, **when** the workflow runs, **then** the exception propagates unchanged and the workflow aborts — identical to today's behavior. No new field needs to be set to preserve this.

A2. **Given** a `Retry` configured with the opt-in "treat-exception-as-failure" policy, `max_attempts=3`, and a body that raises on attempt 1 then returns successfully on attempt 2 with state satisfying the `until` condition, **when** the workflow runs, **then** the `Retry` exits successfully after attempt 2 with the body's output state intact, as if attempt 1 had simply produced a non-passing verdict.

A3. **Given** a `Retry` configured with the opt-in policy and a body that raises on every attempt, **when** the workflow runs and `max_attempts` is exhausted, **then** the `Retry` surfaces a clear, structured failure signal to the parent. The exact signal shape is for the implementation to choose, but it must allow the parent's `Conditional` to route to a `GateAction` the same way it would for a non-passing automated verdict.

A4. **Given** a `Retry` configured with the opt-in policy and a body that raises partway through after mutating some state, **when** the next attempt begins, **then** the body sees the state as it was before the failed attempt — no partial mutations are carried forward.

A5. **Given** any `Retry` invocation under the opt-in policy where the body raises one or more times, **when** the run's artifacts are inspected, **then** each raised exception is captured with at minimum: the exception class name, the exception message, the attempt number it occurred on, and a timestamp. (Stack-trace capture is a desirable enrichment but not required for this AC.)

A6. **Given** any existing `Retry` consumer in the codebase that does not set the new policy field, **when** the existing consumer's tests are re-run after this capability lands, **then** all tests pass with no code changes to the consumer. (Verified by running the existing Agent Foundry and Archipelago test suites.)

---

## Capability B — Configurable AICall Executor

### Capability-Specific Intent

Add an `executor` field to `AICall` whose type and shape mirror the existing `AgentAction.executor` field. The default value is `invoke_ai_call` so today's `AICall` consumers see no behavioral change. Consumers that need custom inference behavior — mocking, wrapping with metrics, synthesizing fallback verdicts on exception, swapping backends, caching — pass their own callable.

The executor contract follows `AgentAction`'s precedent: the callable receives the `AICall` primitive and the resolved `model_input` as keyword arguments, and returns an instance of the AICall's output type `O` (or an awaitable of one). The framework's existing state-update validation enforces output typing; the executor is not exempt.

### Capability-Specific Constraints

- The new `executor` field's default value must be `invoke_ai_call` so existing `AICall` consumers observe no behavioral change.
- The executor contract (callable signature, return type) must match the existing `AgentAction.executor` precedent. Two parallel primitives with the same conceptual hook should not have divergent contracts.
- Output-type validation must remain framework-enforced. A custom executor that returns the wrong type fails the same way the default executor would fail with the same return value — the executor cannot bypass `O`-typing.
- The eval-registry integration for `AICall` (`agent_foundry.evals.registry`) must continue to work for both default-executor and custom-executor AICalls. Evaluations of an AICall configured with a custom executor must run against the configured executor, not against the default.

### Capability-Specific Acceptance Criteria

B1. **Given** an `AICall` configured without specifying an `executor`, **when** it is invoked by the compiler, **then** behavior is identical to today (the default `invoke_ai_call` runs). All existing `AICall` consumers observe no behavioral change.

B2. **Given** an `AICall` configured with a custom synchronous callable as `executor`, **when** it is invoked by the compiler, **then** the custom callable is called with the same arguments the default would receive (the primitive and the resolved `model_input`), and its return value is used as the AICall's output, subject to the framework's existing output-type validation.

B3. **Given** an `AICall` configured with a custom asynchronous callable as `executor`, **when** it is invoked by the compiler, **then** the awaitable returned by the executor is awaited and the result is used as the AICall's output. Sync and async executors must be supported by the same field with no distinction at declaration time.

B4. **Given** an `AICall` whose custom executor returns a value of the wrong type (not an instance of the AICall's output type `O`), **when** it is invoked, **then** the framework's existing output-type validation fires and the call fails the same way it would for an invalid default-executor result.

B5. **Given** an `AICall` whose custom executor catches an underlying inference exception and returns a synthesized output of type `O`, **when** the AICall is wrapped in a `Retry`, **then** the `Retry` sees a normal output and applies its `until` condition as usual — no exception ever reaches the `Retry`. (This is the primary motivating use case for the design-review pipeline in Archipelago.)

B6. **Given** an `AICall` registered with the `AICallRegistry` for evaluation and configured with a custom executor, **when** the eval framework invokes the AICall via its registered name, **then** the custom executor runs (not the default), proving the eval pathway respects the configured executor.

---

## Interaction Model

The two capabilities operate at different layers and do not conflict at the framework level. Their composition is well-defined by where each one fires in the call sequence:

1. The compiler invokes the `Retry` body.
2. The body's `AICall` runs its configured executor.
3. The executor either returns a value of type `O`, or raises.
4. **If the executor returns:** the AICall produces an output, the `Retry` body completes, the `until` condition is checked, and `Retry` either exits or attempts again. The Retry exception policy is moot (no exception was raised).
5. **If the executor raises:** the exception propagates up through the body. The `Retry` body-exception policy applies — either the exception propagates further (default policy) or it consumes an attempt and `Retry` continues (opt-in policy).

**Guidance for consumers — which capability to reach for first:**

- **Reach for Capability B (custom AICall executor) when** you want fine-grained control over the inference call itself — exception handling that synthesizes a domain-specific fallback verdict, structured logging/metrics around inference, mocking for tests, swapping backends per primitive, caching. The custom executor can shape what `O` value the AICall produces on failure, which gives downstream control flow (including the `Retry`'s `until` condition and any parent `Conditional`) more information to act on than a bare "exception occurred."
- **Reach for Capability A (Retry exception policy) when** the body is fallible in ways the consumer would rather not (or cannot) wrap at the primitive level. `AgentAction`s whose containers crash, `FunctionAction`s calling external services, `Sequence`s whose steps fail unpredictably — these benefit from `Retry`'s policy without each primitive needing its own exception-handling shim. The policy is also the right tool when the consumer just wants "treat any failure as a non-passing attempt" with no need to discriminate why the failure happened.
- **Use both together** when the AICall's exception handling synthesizes meaningful fallback verdicts that drive `until` (Capability B), while the surrounding `Retry` body also contains other fallible primitives whose exceptions should be tolerated rather than propagated (Capability A). In this combined case, the AICall's executor handles AICall-specific failures inline, and the `Retry` policy catches failures from siblings the executor doesn't cover.

**Composition acceptance criterion:**

I1. **Given** a `Retry` whose body is a `Sequence[ai_call_with_custom_executor, fallible_function_action]`, with the `Retry` configured for the opt-in exception policy and the AICall's custom executor configured to catch underlying inference exceptions and return a synthesized verdict, **when** the workflow runs and (a) the underlying inference raises but the AICall's executor catches it and returns a synthesized verdict, **and separately when** (b) the `FunctionAction` raises, **then** in case (a) the `Retry` sees a normal AICall output and proceeds without the exception policy firing, and in case (b) the `Retry` body-exception policy fires and treats the `FunctionAction`'s exception as a consumed attempt. Both behaviors must hold together with no implicit coupling between the two capabilities beyond the call-order semantics described above.
