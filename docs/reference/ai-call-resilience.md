# AICall Resilience Reference

`AICall` is the single-call model inference construct. Its resilience behavior
lives at the model-provider boundary so application workflows do not need to
wrap every model call with local retry and failover code.

## Current Behavior

An `AICall[I, O]` can:

- retry transient provider failures against the same model
- fail over to alternate `ModelEntry` targets
- enforce a per-call timeout at the compiler node
- validate provider or executor output against the declared output model `O`
- emit lifecycle events and OpenTelemetry spans for call start, completion, and
  failure

The default provider path is implemented by
`agent_foundry.ai_models.execute.invoke.invoke_ai_call`.

## Retry Policy

`AICall.retry` accepts a `RetryPolicy`.

```python
from agent_foundry.ai_models.resilience import RetryPolicy

RetryPolicy(
    max_attempts=3,
    backoff_base_seconds=0.5,
    backoff_max_seconds=8.0,
)
```

`max_attempts` is the total number of tries for one model. `1` means no retry.
Backoff is exponential and capped by `backoff_max_seconds`.

When `AICall.retry` is `None`, Agent Foundry uses `DEFAULT_RETRY_POLICY`, which
currently retries up to three attempts per model.

## Transient Classification

Providers decide whether an exception is transient by implementing
`InferenceProvider.is_transient(exc)`.

The built-in OpenAI and Anthropic providers classify these as transient:

- timeouts
- connection errors
- rate limits
- 5xx/provider-overloaded responses

Non-transient errors are not retried against the same model. Examples include
bad requests, authentication failures, invalid parameters, and programmer
errors.

## Failover

Failover is separate from retry.

`AICall.fallbacks` controls the model chain:

- `None`: derive fallbacks from `ModelEntry.fallback`
- `[]`: disable failover
- non-empty list: use that explicit fallback chain

For each candidate model, Agent Foundry applies the retry policy first. If that
candidate still fails, execution advances to the next fallback. If all
candidates fail, the last exception is raised.

## Custom Executors

`AICall.executor` is an async escape hatch:

```python
async def executor(*, construct, model_input):
    ...
```

When set, the custom executor bypasses the default provider path. Built-in
retry/failover behavior applies only if the executor calls `invoke_ai_call`
itself.

Custom executors still get:

- timeout enforcement
- output type validation
- lifecycle start/completion/failure events
- span wrapping

Custom executors do not contribute token usage to `AI_CALL_COMPLETED`; only the
default provider path reports usage.

## Timeout

`AICall.timeout_seconds` sets the compiler-node deadline for both the default
provider path and async custom executors. Timeout raises
`ConstructTimeoutError` and emits an `AI_CALL_FAILED` lifecycle event when a run
context is active.

## Observability

The compiler emits:

- `AI_CALL_STARTED`
- `AI_CALL_COMPLETED`
- `AI_CALL_FAILED`

Completion events include token usage when the provider reports it. AICall spans
record the construct type, run id, input model, output model, and chat operation
name.

Retry attempts are currently logged, but they are not emitted as lifecycle
events or span events.

## Current Gaps

These are known gaps, not implemented behavior:

- No retry-history or exhaustion wrapper exception; when all candidates fail,
  the last exception is re-raised.
- Retry attempts are not represented in lifecycle events or telemetry spans.
- Structured-output validation failures are not separately classified as
  recoverable versus programmer/schema errors.
- AICall outputs are not persisted as per-node artifacts. AgentAction turns
  write output artifacts; AICall currently returns validated state only.

## Test Coverage

Current tests cover:

- transient retry and success
- retry exhaustion
- persistent-error failover without retry
- failover after transient retry exhaustion
- explicit `fallbacks=[]` disabling model-chain failover
- `fallbacks=None` inheriting `ModelEntry.fallback`
- default retry policy behavior
- timeout enforcement for default provider path and custom executors
- compile-time rejection of sync custom executors
- output validation for provider and custom executor returns
- lifecycle start/completion/failure events
- token usage on completion events
- OpenTelemetry span success/error behavior

Important remaining coverage gaps:

- no test for retry-attempt lifecycle or span events because the feature does
  not exist yet
- no test for retry-history exception content because the feature does not exist
  yet
- no artifact-persistence tests for AICall output because the feature does not
  exist yet
