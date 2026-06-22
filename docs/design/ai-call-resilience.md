# AICall Resilience

## Status

Shell design. Requirements capture only; detailed architecture deferred.

## Problem

`AICall` currently delegates a single inference attempt to the configured provider. When the provider fails transiently, callers must either let the exception abort the process or build local wrapper executors that translate infrastructure failures into domain outputs.

That pushes provider resilience into product-level designs. In Archipelago's design-review loop, for example, a transient reviewer failure can cause the surrounding `Retry` to rerun an expensive Designer step even though only the reviewer inference failed. Resilience should live at the `AICall` boundary so products can rely on consistent retry behavior for single-call inference.

## Goals

- Give `AICall` built-in retry behavior for transient inference failures.
- Keep domain retry loops focused on domain failure, not provider instability.
- Preserve fail-fast behavior for configuration, authentication, permission, and programmer errors.
- Make retry behavior observable in lifecycle events, logs, or telemetry.
- Keep the default behavior backward-compatible unless a deliberate default change is approved.

## Requirements

- `AICall` can retry transient provider failures locally before surfacing failure to the parent construct.
- Transient failures include, at minimum:
  - provider 5xx responses
  - request timeouts
  - connection errors
  - rate-limit responses after SDK-internal retries are exhausted
- Structured-output recoverability is considered separately from transport/provider failures. Missing tool-use blocks and output validation failures may be retryable, but the design must decide retry bounds and classification explicitly.
- Non-transient failures propagate immediately, including:
  - authentication errors
  - permission errors
  - bad-request errors caused by invalid model IDs, invalid parameters, or malformed requests
  - prompt/instruction resolver bugs
  - unexpected programmer errors
- Retry policy is configurable per `AICall` or through a reusable default policy.
- Retry policy includes a bounded attempt count and backoff strategy.
- Exhausted retries surface a clear exception that preserves the original failure details and retry history.
- Lifecycle/telemetry should record retry attempts without requiring product code wrappers.
- Product-supplied custom `AICall.executor` behavior must be accounted for: the design should decide whether built-in resilience wraps custom executors, only the default executor, or is opt-in for custom executors.

## Non-Goals

- Do not add domain-specific fallback outputs to Agent Foundry. Products remain responsible for deciding whether an exhausted AICall should become a domain verdict, abort, or operator escalation.
- Do not retry broad process bodies. This feature is scoped to single-call inference resilience.
- Do not mask non-transient configuration or programmer errors.

## Related: AICall output artifacts

A separate gap surfaced alongside resilience work: `AICall` nodes leave **no
artifact record** of their structured output. AgentActions get a per-node
artifact subdirectory in the run (e.g. `runs/<id>/designer/`); FunctionActions
and AICalls write nothing. When an AICall is the meaningful unit of work — a
reviewer producing a verdict, a classifier producing a label — there is no
durable record of what it returned, only what downstream state happened to
retain.

Today products work around this by routing the output through a downstream
FunctionAction that holds the value and writes it (Archipelago's design-review
aggregator persists `design-review/attempt-N.json` this way). That works but
is per-product boilerplate, and it only captures AICalls whose output a later
in-process node already touches.

**Suggested generic capability:** let `AICall` optionally persist its validated
structured output to a per-node artifact directory, parallel to AgentActions —
e.g. `runs/<id>/<name-or-node_id>/output.json` via `model_dump_json`. This
would give every AICall a record for free, attributed by the construct's
`name` (see leaf-node naming), without a custom executor.

Design considerations to resolve if pursued:

- **Opt-in vs. default** — mirror the retry-policy decision above; writing every
  AICall output by default may be surprising and may duplicate large payloads.
- **Naming/uniqueness** — the artifact path needs a stable, collision-free key;
  `node_id` is unique within the compiled graph, `name` is human-readable but
  not guaranteed unique. Likely `<name>-<node_id>` or `node_id` with `name` in
  the file body.
- **Redaction** — outputs may carry sensitive content; artifact writing must
  honor the same redaction policy used for telemetry spans.
- **Relationship to lifecycle events** — the payload belongs in an artifact, not
  in `lifecycle.jsonl` (a wire-stable event stream); the lifecycle event should
  at most reference the artifact path.

This is observability, not resilience, but it shares the same boundary
(`AICall`) and the same "products shouldn't need wrapper executors" principle,
so it is captured here pending its own design.

## Open Questions

- Should the retry policy default to enabled for all `AICall`s, or require explicit opt-in?
- Which exception taxonomy should Agent Foundry expose so products do not depend on provider-specific SDK classes?
- Should output validation failures retry by default, or require opt-in because they may indicate prompt/schema bugs?
- How should retry events appear in `lifecycle.jsonl` and telemetry spans?
- How should this interact with provider SDKs that already perform internal retries?
