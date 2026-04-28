# Agent Foundry

A platform for defining, running, and managing agent systems.

## Authentication

ACP containers require exactly one of these environment variables:

**Option 1: OAuth token (Claude Pro/Max subscription)**
```bash
claude setup-token          # generates a long-lived token
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-..."
```

**Option 2: API key (API billing)**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

The `DEFAULT_ENV_ALLOWLIST` in `acp/container.py` passes these from the host environment into containers. The entrypoint script validates that exactly one auth method is present and rejects the container if both or neither are set.

## Lifecycle events: platform vs. domain

Agent Foundry writes an append-only event stream to `<run_dir>/lifecycle.jsonl` during every run. Events fall into two categories:

**Platform events** — a fixed, enumerated vocabulary owned by Agent Foundry. Emitted by the executor, registry, and compiler nodes. Examples: `run_started`, `agent_container_started`, `agent_invocation_started`, `turn_started`, `turn_completed`, `responder_requested`, `function_action_started`, `run_ended`. The full list is `LifecycleEvent` in `agent_foundry/orchestration/lifecycle_events.py`. Products do not define new platform events and do not emit these types themselves.

**Domain events** — open-schema, product-defined. Products emit their own events via `run_ctx.lifecycle_writer.append_run_event(...)` from within a `FunctionAction`'s function or any other code that has access to the `AgentRunContext`. The convention is:

```python
run_ctx.lifecycle_writer.append_run_event(
    "step_committed",                            # product-chosen kind subtype
    # ...any additional fields the product wants to record...
)
```

The helper stamps `type=LifecycleEvent.DOMAIN` (= `"domain"`) itself; products only supply the kind and extra fields. `DOMAIN` is the **escape hatch** that lets a product extend the lifecycle stream with its own vocabulary without needing to modify Agent Foundry's enum. Consumers of the jsonl (e.g., a product-specific summary renderer) filter by `type == "domain"` and route on the `kind` subfield. Downstream examples: Archipelago's planned `summary.txt` renderer that groups a run's activity by change set and step — each boundary is emitted as a `DOMAIN` event with a `kind` like `"change_set_started"` or `"step_completed"`.

Rule of thumb: if the event describes something the platform does (start a container, run a turn, invoke a function), that's a platform event — emitted automatically. If the event describes something the *product* does (commit a change set, escalate to a human, mark a review cycle complete), that's a `DOMAIN` event — the product emits it explicitly.

## MLflow Integration

Agent Foundry can emit OpenTelemetry spans at primitive boundaries and bind each plan run to an MLflow Run. The integration ships in two pieces:

- **`agent_foundry.telemetry`** (always installed) — vendor-neutral OTel emission. Exports `TelemetryConfig`, `RunDefinition`, `RedactionPolicy`, `RunStats`, `ArtifactSpec`, `build_tracer_provider`, and `emit_span`. The compiler wraps every `AgentAction` execution with `emit_span`, sets `gen_ai.operation.name = "chat"`, and applies any product-supplied redaction.
- **`agent_foundry.mlflow_adapter`** (optional, requires the `[mlflow]` extra) — translates AF span attributes to MLflow's namespace at emit time and binds MLflow Run start/end to the run lifecycle.

### Install

```bash
pip install agent-foundry[mlflow]
```

The bare install excludes MLflow. Importing `agent_foundry.mlflow_adapter` without the extra raises an actionable `ImportError` pointing at this command.

### Wire it up in your product

Two sides of the integration share an experiment but configure separately because they target different APIs:

- **Trace spans** flow over OTLP/HTTP. Routing to a specific MLflow experiment uses the `x-mlflow-experiment-id` header on `TelemetryConfig.otlp_headers`. The runner builds the OTLP exporter with these headers when you call `run_primitive_plan(..., telemetry=config)`, so set them before the run starts.
- **Run data** (params, metrics, tags, artifacts via `mlflow.log_*`) uses the `mlflow` client library's global state. `enable()` sets that state for you when you pass `tracking_uri` and `experiment_id`.

```python
import os

from agent_foundry.mlflow_adapter import MLFLOW_TRANSLATIONS, enable as enable_mlflow_adapter
from agent_foundry.orchestration.runner import run_primitive_plan
from agent_foundry.telemetry import RunDefinition, TelemetryConfig

MLFLOW_BASE_URL = os.environ.get("MLFLOW_BASE_URL", "http://localhost:5000")
EXPERIMENT_ID = os.environ["MLFLOW_EXPERIMENT_ID"]   # the single source of truth

config = TelemetryConfig(
    otlp_endpoint=f"{MLFLOW_BASE_URL}/v1/traces",
    otlp_headers={"x-mlflow-experiment-id": EXPERIMENT_ID},
    service_name="my-product",
    attribute_translations=MLFLOW_TRANSLATIONS,    # mirrors agent_foundry.* to mlflow.*
    run_definition=RunDefinition(
        name=lambda inp: f"ticket-{inp.ticket_id}",
        params=lambda inp: {"ticket_id": inp.ticket_id, "kind": inp.kind},
        tags={"product": "my-product"},
        metrics=lambda out, stats: (
            {"duration_ms": stats.duration_ms, "success": float(out.success)}
            if out is not None
            else {"duration_ms": stats.duration_ms}
        ),
    ),
)


def attach_mlflow(ctx) -> None:
    enable_mlflow_adapter(
        config=config,
        run_context=ctx,
        input_model=plan_input,
        tracking_uri=MLFLOW_BASE_URL,
        experiment_id=EXPERIMENT_ID,
    )


await run_primitive_plan(
    plan,
    initial_state=plan_input,
    artifacts_dir=artifacts_dir,
    workspace_volume=workspace_volume,
    base_image_tag=base_image_tag,
    responder_provider=responder_provider,
    telemetry=config,
    on_open=[attach_mlflow],
)
```

### Setting the experiment ID

Pick one source of truth (env var, config file, hardcoded) and reference it in two places:

1. `TelemetryConfig.otlp_headers["x-mlflow-experiment-id"]` — for trace routing.
2. `enable(..., experiment_id=...)` — for `mlflow.start_run` / `log_params` / `log_metrics`.

If you skip the `tracking_uri` and `experiment_id` kwargs to `enable()`, the MLflow client falls back to its standard env vars (`MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT_ID`). The OTLP header is always required for trace routing — there is no env var fallback for that side.

### Turning telemetry on and off

`telemetry` is an opt-in parameter on `run_primitive_plan`. Pass `None` (or omit) and AF emits no spans, builds no provider, and never imports MLflow. Pass a `TelemetryConfig` and AF builds a per-run `TracerProvider`, anchors it on `RunContext.telemetry_provider`, runs the plan with span emission active, and shuts the provider down on exit. Per-run isolation: the runner never calls `trace.set_tracer_provider`, so concurrent runs in the same process never overwrite each other's providers.

The MLflow adapter is independent — call `enable_mlflow_adapter` from an `on_open` hook only when you want MLflow Run binding. Span emission works without the adapter (you just don't get a wrapping MLflow Run with params/metrics/artifacts).

### Local verification demo

A working end-to-end example lives at `examples/mlflow_demo/`. It includes a `docker-compose.yaml` that brings up a local MLflow 3.7 server with SQLite persistence, a `main.py` showing the wiring above, and a smoke test (`tests/agent_foundry/mlflow_adapter/test_verification_demo.py`, gated by `AF_LIVE_MLFLOW=1`). See `examples/mlflow_demo/README.md` for setup steps.
