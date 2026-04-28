# MLflow Tracing Integration

## Purpose

Deliver MLflow's tracing and run capability in Agent Foundry without coupling the platform to MLflow's SDK. Spans flow over OpenTelemetry; runs are bound through a small, optional adapter. Products opt in by passing a config object; absence of the config means no emission.

## Goals

- AF emits OpenTelemetry spans at primitive boundaries.
- Each AF run (execution of a primitive plan via `run_primitive_plan`) maps to one MLflow Run with product-declared params, metrics, tags, and artifacts.
- Products configure emission per environment via their own deployment infra; AF reads no environment variables.
- Sensitive fields can be redacted before they leave AF.
- Spans land in a self-hosted MLflow instance and render with typed span types, structured inputs/outputs, and run association.

## Non-goals

- Span coverage on every primitive type (this stage covers `AgentAction` only; other primitives land later).
- Sampling.
- AI Gateway / multi-provider routing.
- Prompt Registry backing for callable fields.
- `mlflow.evaluate` integration, judges, dataset promotion, assessments.
- Search/query API surfacing in AF.
- Active validation against non-MLflow OTel backends.

## Architecture

Two new modules. They share `trace_id` and `run_id` as the only handoff.

```
┌──────────────────────────────────────────────────────────────────┐
│  src/agent_foundry/telemetry/        (AF core, vendor-neutral)   │
│   • TelemetryConfig                                              │
│   • RunDefinition                                                │
│   • RedactionPolicy                                              │
│   • OTel SpanProcessor / Exporter setup                          │
│   • Span emission helpers used by the compiler                   │
│                                                                  │
│   Depends on: opentelemetry-sdk, opentelemetry-exporter-otlp     │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  src/agent_foundry/mlflow_adapter/   (optional install extra)    │
│   • Translation: agent_foundry.* span attrs → mlflow.* attrs     │
│   • Run lifecycle: start_run on RunContext open,            │
│     end_run on close, log_metric / log_param / log_artifact      │
│   • Run-id propagation as an OTel span attribute                 │
│                                                                  │
│   Depends on: mlflow, plus everything in telemetry               │
└──────────────────────────────────────────────────────────────────┘
```

The `mlflow_adapter` lives behind an extras install:

```
pip install agent-foundry[mlflow]
```

AF core never imports `mlflow`. The string `mlflow` only appears inside the adapter module.

## Run boundary

AF already has a per-plan-execution context — currently named `AgentRunContext` in `src/agent_foundry/orchestration/run_context.py` — with `run_id`, `artifacts_dir`, `lifecycle_writer`. The "Agent" prefix is a misnomer left over from an earlier iteration: the context is constructed in `run_primitive_plan` *before* the compiled graph runs and stays active for every primitive (`Sequence`, `Loop`, `AgentAction`, `FunctionAction`, …) the plan executes. AF already uses the noun "run" to mean a full plan execution (`run_id`, `RUN_STARTED` lifecycle event, `run_primitive_plan`, `current_run_context` ContextVar).

**This work renames the class `AgentRunContext` → `RunContext`** to drop the misleading prefix and match AF's own vocabulary. References in `container_executor.py`, `runner.py`, and `runtime/__init__.py` move with it. Mechanical change; the symbol and its 9 call sites are enumerated by LSP `findReferences`.

For this stage, **one `RunContext` lifecycle = one MLflow Run**. The boundary is the platform invocation. Products that need finer or coarser boundaries within a single invocation are out of scope; that need is addressed later by an in-tree scope primitive if it materializes.

## RunDefinition

The product knows what to record about a run; AF doesn't. The `RunDefinition` is how the product declares run shape:

```python
class RunDefinition(BaseModel):
    name:      Callable[[BaseModel], str]
    params:    Callable[[BaseModel], dict[str, Any]]
    tags:      dict[str, str] | Callable[[BaseModel], dict[str, str]]
    metrics:   Callable[[BaseModel, RunStats], dict[str, float]]
    artifacts: list[ArtifactSpec] = Field(default_factory=list)
```

Each callable receives the plan's input model (the same `I` the root primitive declares). `metrics` additionally receives a `RunStats` summary computed at run close (total spans, duration, error count, aggregate token usage from spans).

`ArtifactSpec` describes a file path on disk to log to the MLflow run as an artifact (commonly `artifacts_dir / something`).

There is no default `RunDefinition`. If telemetry is on but no `RunDefinition` is supplied, spans flow but no MLflow run is created. Loud, predictable. Matches AF's "no default for semantic choices" rule.

## TelemetryConfig

The product's opt-in object. Constructed at process startup, passed to the runtime entry point.

```python
class TelemetryConfig(BaseModel):
    otlp_endpoint:     str                               # e.g. "http://localhost:5000/v1/traces"
    otlp_headers:      dict[str, str]                    # e.g. {"x-mlflow-experiment-id": "1"}
    service_name:      str                               # OTel resource attribute
    redaction:         RedactionPolicy | None = None
    run_definition:    RunDefinition | None = None
```

Product code, in startup:

```python
config = TelemetryConfig(
    otlp_endpoint=os.environ["AF_OTLP_ENDPOINT"],
    otlp_headers={"x-mlflow-experiment-id": os.environ["AF_EXPERIMENT_ID"]},
    service_name="archipelago",
    run_definition=ARCHIPELAGO_RUN_DEFINITION,
) if "AF_OTLP_ENDPOINT" in os.environ else None

await run_primitive_plan(plan, input, telemetry=config, ...)
```

Per-environment enable/disable lives in the product's deployment infra (env vars, k8s configmaps, etc.). The platform reads no environment.

## Attribute namespace contract

AF emits attributes in two namespaces:

- `agent_foundry.*` — AF-internal concepts that no external standard covers cleanly.
- `gen_ai.*` — OTel GenAI semantic conventions, used as-is for things the standard covers.

| Attribute                          | Source     | Set by               | Purpose                                       |
|------------------------------------|------------|----------------------|-----------------------------------------------|
| `agent_foundry.primitive_type`     | AF         | telemetry            | "AgentAction", "Sequence", …                  |
| `agent_foundry.primitive_name`     | AF         | telemetry            | The primitive's `name` field if present       |
| `agent_foundry.input`              | AF         | telemetry            | JSON of input model (post-redaction)          |
| `agent_foundry.output`             | AF         | telemetry            | JSON of output model (post-redaction)         |
| `agent_foundry.run_id`             | AF         | telemetry            | The `RunContext.run_id`                  |
| `gen_ai.operation.name`            | OTel GenAI | telemetry            | "chat" for AgentAction LLM invocations        |
| `gen_ai.request.model`             | OTel GenAI | executor             | Model id reported by executor                 |
| `gen_ai.usage.input_tokens`        | OTel GenAI | executor             | Token usage if executor reports it            |
| `gen_ai.usage.output_tokens`       | OTel GenAI | executor             | "                                             |

The MLflow adapter translates only the AF-internal namespace:

| AF attribute                  | MLflow attribute    |
|-------------------------------|---------------------|
| `agent_foundry.input`         | `mlflow.spanInputs` |
| `agent_foundry.output`        | `mlflow.spanOutputs`|
| `agent_foundry.run_id`        | (used to bind the span to the active MLflow run; not re-emitted) |

`gen_ai.operation.name` is recognized natively by MLflow's OTLP translator and renders the typed span without remapping.

The translation is implemented as an OTel `SpanProcessor` registered when the MLflow adapter is enabled. No collector required for this stage.

**Translation is additive, not destructive.** The `SpanProcessor` sets the `mlflow.*` attributes on the span without removing or mutating the original `agent_foundry.*` attributes. After translation the exported span carries both namespaces. This preserves the `agent_foundry.*` contract for any future second backend (Tempo, Honeycomb, Langfuse, an alternate adapter) that reads from the canonical namespace, and keeps the MLflow-specific names from leaking back into AF core's surface. MLflow ignores attributes it doesn't recognize, so the residual `agent_foundry.*` attributes are harmless on the MLflow side and may be useful for forensic queries.

This contract is versioned. Changes to attribute names are breaking changes; downstream consumers depend on them.

## Span emission points (this stage)

The compiler wraps `AgentAction` node functions with span emission. Span boundaries:

- **Start** — entering `_compile_agent_action`'s `node_fn_async` / `node_fn_sync`.
- **End** — when the executor returns (success) or raises (error). Status reflects the outcome.

Other primitives (`Sequence`, `Loop`, `Retry`, `Conditional`, `FunctionAction`, `GateAction`) emit no spans this stage. Their span coverage is the next stage's work.

## Redaction

`RedactionPolicy` is a callable that scrubs values before they become span attributes:

```python
class RedactionPolicy(BaseModel):
    redact_input:  Callable[[BaseModel], BaseModel] | None = None
    redact_output: Callable[[BaseModel], BaseModel] | None = None
```

Both callables receive a deep copy of the model and return a redacted copy. If a callable is unset, the model serializes as-is. Keeping these as model→model callables (rather than dict→dict) preserves Pydantic typing through the redaction path.

The same policy applies to `RunDefinition.params` outputs before they're logged as MLflow params.

For this stage, redaction is wired through but products may pass `None` and accept that everything goes on the wire. Wiring it through now means turning it on later is a config change, not a code change.

## Run lifecycle (MLflow adapter)

The adapter listens to `RunContext` lifecycle events. Two existing observation points are sufficient:

- **Open** — when `run_primitive_plan` constructs the `RunContext` and sets it on the `current_run_context` ContextVar.
- **Close** — when the plan exits (success or exception).

On open:
1. Resolve the active `RunDefinition` from `TelemetryConfig`.
2. If absent, do nothing (spans still flow, no MLflow run).
3. If present, evaluate `name(input)`, `params(input)`, `tags(input)`. Apply redaction to params.
4. Call `mlflow.start_run(run_name=..., tags=...)`. Log params via `mlflow.log_params`.
5. Stash the MLflow `run_id` on the `RunContext` for telemetry to attach to spans.

On close:
1. Compute `RunStats` (duration, span count, error count, aggregate token usage).
2. Evaluate `metrics(final_state, stats)`. Log via `mlflow.log_metrics`.
3. For each `ArtifactSpec`, log via `mlflow.log_artifact`.
4. Call `mlflow.end_run(status=...)` reflecting success or failure.

The adapter must hook the `RunContext` lifecycle without modifying it. Implementation note: extend `RunContext` (or its construction site) with optional open/close hooks the adapter registers — same shape as the existing `lifecycle_writer`.

## File layout

```
src/agent_foundry/
  telemetry/
    __init__.py
    config.py            # TelemetryConfig, RunDefinition, ArtifactSpec, RedactionPolicy
    attributes.py        # canonical attribute name constants
    spans.py             # span emission helpers used by the compiler
    setup.py             # OTel SDK setup (TracerProvider, exporter, span processors)
  mlflow_adapter/
    __init__.py
    translation.py       # OTel SpanProcessor mapping agent_foundry.* → mlflow.*
    run_lifecycle.py     # start_run / end_run hooks bound to RunContext lifecycle
    extras.py            # optional-dependency import guard
```

`docs/design/mlflow-tracing-integration.md` (this doc).

Tests under `tests/agent_foundry/telemetry/` and `tests/agent_foundry/mlflow_adapter/`.

## Dependencies

- AF core (existing dependencies stay) — adds `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http` to the base install.
- MLflow adapter — adds `mlflow` (≥ 3.6.0 for OTLP ingest, ≥ 3.7.0 if compression is wanted) under an `[mlflow]` extra.

The dead `ExecutionTracer` in `src/agent_foundry/observability/tracer.py` is deleted as part of the first commit; the file shape was a prior iteration with no live call sites.

## Verification Demo

End-to-end demo that proves every interface boundary in this design works together. This is not a scope-limiting slice; it is the acceptance gate for the design as a whole — a compact scenario that, when passing, demonstrates the full design works as specified.

1. `TelemetryConfig` constructed in a small example product.
2. One `AgentAction` declared, wrapped in a plan.
3. Plan invoked via `run_primitive_plan(...)` with `telemetry=config`.
4. Compiler emits an OTel span for the `AgentAction` execution.
5. Span exports over OTLP/HTTP to a local MLflow server.
6. MLflow adapter creates a Run on `RunContext` open, ends it on close, logs the product's declared params/metrics/tags.
7. Trace appears in MLflow UI with typed span (AgentAction → CHAT/AGENT span type), structured inputs/outputs, and bound to the run.

Verification:

- Visual: MLflow UI shows the run, the trace, and the span with structured I/O.
- Programmatic: a smoke test that runs the example plan and queries MLflow's API for the resulting run and trace, asserts on the recorded params and metrics.

## Open items

- The OTLP-ingest path interacts with assessments / dataset promotion / prompt-version linkage in ways not explicitly documented. Not on the critical path for this stage; flagged for the stage that adds those features.
- Concurrency model: how the OTel `current_run_context`-bound state coexists with AF's own `current_run_context` ContextVar under asyncio. Likely a non-issue (independent ContextVars), but worth a smoke test under concurrent runs before declaring done.
- **Hard-kill orphaned MLflow runs.** SIGTERM is handled cooperatively — the runner installs SIGINT/SIGTERM handlers that set `cancel_event`, the graph unwinds, `on_close` fires with a `CancelledError`, and the MLflow adapter ends the run as `FAILED`. SIGKILL and OOM-kill cannot run any cleanup code, so the MLflow run remains stuck in `RUNNING` indefinitely. There is no per-run heartbeat or server-side timeout. Acceptable for this stage; flagged for production-ops follow-up (e.g. a janitor sweeping stale `RUNNING` runs after a TTL).

---

## Possible later work

### Coverage

Span emission on every primitive boundary: `Sequence`, `Loop`, `Retry`, `Conditional`, `FunctionAction`, `GateAction`. Token-usage rollup at composite boundaries. Tail-based sampling.

### Prompt Registry

Callable-field backing for `prompt_builder` / `instructions_provider` resolved from MLflow's Prompt Registry by alias (`@production`, `@canary`, …). Prompt-version linkage on spans (`mlflow.prompt.name`, `mlflow.prompt.version`). Smoke-test verification that prompt-version linkage works on OTLP-ingested traces.

### Evaluation and curation

`mlflow.evaluate` integration: any AF primitive compiles to a `predict_fn` runnable against an evaluation dataset. Built-in scorers for AF properties (schema fidelity, instruction adherence, latency / cost budgets) plus a custom-scorer extension point. LLM-judge writeback of assessments. Human-feedback writeback via `GateAction`-shaped patterns. Dataset promotion workflow — sampling interesting traces, attaching expected outputs, growing the regression set. This is where the compounding evaluation loop becomes available.

### AI Gateway

Provider-agnostic LLM proxy as an `AgentAction` executor option. Centralized rate limits, cost caps, API-key custody, automatic provider failover. Trigger: AF supports a second LLM provider, or cost-cap / key-rotation pressure becomes real.

### Search and query

Typed AF surface over MLflow's search API (`find_runs`, `find_traces` with structured filters). Trigger: products have enough traffic that programmatic queries beat the UI.

### Artifact persistence patterns

Standardized capture of useful AF by-products into MLflow run artifacts: rendered prompts (variables substituted), compiled LangGraph diagram, intermediate state on failure, captured prompt body that was actually used (defends against later prompt edits invalidating old runs).

### Tags and namespaces

Codified experiment-naming convention (e.g. `<product>/<env>`) and tag schema (tenant, primitive_id, AF version, prompt alias). Product-side helpers without AF imposing defaults.

### Custom run boundaries

In-tree scope primitive for products that need run boundaries that don't align with `run_primitive_plan` invocations (e.g. one platform invocation processing many logical units). Lands when a product actually needs it.

### Non-MLflow backend validation

Active testing against Langfuse / Jaeger / other OTel backends to validate the abstraction. A second adapter to prove portability is real.

### Production operations

Auth, RBAC, deployment patterns for self-hosted MLflow at scale. Triggered by multi-tenant or production-scale deployment.

### Out of scope until further notice

- Classical experiment-tracking workflows (notebook hyperparam sweeps).
- MLflow Model Registry for primitive declarations (force-fit; runs and aliases cover the same ground).
- MLflow Models packaging / Agent Server hosting (wrong shape for AF).
