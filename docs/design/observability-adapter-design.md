# Observability Adapter Design

Agent Foundry's observability design separates framework-owned telemetry from
vendor-specific adapters.

The core framework emits OpenTelemetry spans and lifecycle events using
Agent Foundry attribute names. Adapters translate or consume that evidence for a
specific backend. MLflow is the first implemented observability adapter.

## Goals

- Keep Agent Foundry telemetry vendor-neutral by default.
- Let applications opt in to backend-specific observability without changing
  process declarations.
- Preserve typed input/output evidence at construct boundaries.
- Keep each run isolated: one run's tracer provider must not overwrite another
  run's provider.
- Let MLflow users bind Agent Foundry process runs to MLflow Runs while sending
  spans through OTLP.

## Current Architecture

```text
agent_foundry.telemetry
  TelemetryConfig
  RunDefinition
  RedactionPolicy
  RunStats
  ArtifactSpec
  emit_span(...)
  build_tracer_provider(...)

agent_foundry.mlflow_adapter
  MLFLOW_TRANSLATIONS
  enable(...)
  run lifecycle hooks
```

The core telemetry package depends on OpenTelemetry, not MLflow.

The MLflow adapter is optional:

```bash
pip install agent-foundry[mlflow]
```

## Runtime Flow

1. Application constructs a `TelemetryConfig`.
2. Application passes it to `run_process(..., telemetry=config)`.
3. `run_process` builds a per-run `TracerProvider` and stores it on `RunContext`.
4. Compiler nodes call `emit_span(...)`.
5. `emit_span` resolves the active provider from `current_run_context`.
6. Spans are exported over OTLP/HTTP using the configured endpoint and headers.
7. If MLflow run binding is desired, the application calls
   `mlflow_adapter.enable(...)` from an `on_run_starting` hook.
8. The MLflow adapter attaches run lifecycle hooks that start/end an MLflow Run
   and log params, metrics, tags, and artifacts.

Agent Foundry never calls `trace.set_tracer_provider`; provider isolation is
per run.

## TelemetryConfig

`TelemetryConfig` is the application opt-in object:

```python
TelemetryConfig(
    otlp_endpoint="http://localhost:5000/v1/traces",
    otlp_headers={"x-mlflow-experiment-id": "1"},
    service_name="my-application",
    attribute_translations=MLFLOW_TRANSLATIONS,
    redaction=...,
    run_definition=...,
)
```

If `telemetry=None`, Agent Foundry emits no spans and builds no provider.

## Attribute Contract

Agent Foundry emits framework-owned attributes:

- `agent_foundry.construct_type`
- `agent_foundry.construct_name`
- `agent_foundry.input`
- `agent_foundry.output`
- `agent_foundry.run_id`

It also emits OTel GenAI attributes where applicable:

- `gen_ai.operation.name`
- `gen_ai.request.model`
- `gen_ai.usage.input_tokens`
- `gen_ai.usage.output_tokens`

These names are part of the telemetry contract. Changing them is a breaking
change for downstream consumers.

## Adapter Translation

MLflow expects some span fields under MLflow-specific attribute names. Agent
Foundry handles this through `TelemetryConfig.attribute_translations`, a plain
mapping from source attribute to mirrored backend attribute.

The MLflow adapter exports:

```python
MLFLOW_TRANSLATIONS = {
    "agent_foundry.input": "mlflow.spanInputs",
    "agent_foundry.output": "mlflow.spanOutputs",
}
```

Translation happens at emit time inside `emit_span`, not in an OTel
`SpanProcessor`. This is deliberate: setting attributes after a span ends can be
dropped by the OTel SDK, especially with batch processors. Emit-time mirroring
keeps the core vendor-neutral while ensuring both attributes are present before
the span closes.

## RunDefinition

`RunDefinition` declares the MLflow Run shape:

```python
RunDefinition(
    name=lambda input_model: "run-name",
    params=lambda input_model: {"case": input_model.case_id},
    tags={"application": "my-app"},
    metrics=lambda output_model, stats: {"duration_ms": stats.duration_ms},
    artifacts=[...],
)
```

The MLflow adapter evaluates:

- `name`, `params`, and `tags` at run start
- `metrics` and `artifacts` at run end

On failed runs, the output model passed to `metrics` is `None`.

## Redaction

`RedactionPolicy` can redact input and output models before they become span
attributes. Redaction functions receive and return Pydantic models.

Redaction applies to span input/output. MLflow params should be derived
carefully by application code; the adapter applies configured input redaction
before evaluating run params.

## Current Span Coverage

Current span coverage includes:

- `AgentAction`
- `AICall`

Current lifecycle events cover more runtime activity than spans. Span coverage
for `Sequence`, `Loop`, `Retry`, `Conditional`, `FunctionAction`, and
`GateAction` remains future work.

## Current Gaps

- `RunStats.duration_ms` is live, but span count, error count, and token totals
  are currently zero placeholders.
- MLflow run binding is not automatic from `TelemetryConfig`; applications call
  `mlflow_adapter.enable(...)` from a run hook.
- There is no broad end-to-end MLflow server smoke test in normal unit tests.
- No second observability backend has been implemented yet to prove adapter
  portability beyond MLflow.

## Fit With The Framework Pivot

This design fits the OSS/framework pivot:

- OpenTelemetry is the framework-owned telemetry substrate.
- MLflow is an optional adapter.
- Backend-specific attribute names live in adapter-provided translation tables.
- Run metadata is application-declared through `RunDefinition`.
- The same core span attributes can feed future adapters.
