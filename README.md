# Agent Foundry

**A platform for building agentic workflow systems.** Agent Foundry provides composable,
typed constructs that compile to executable [LangGraph](https://github.com/langchain-ai/langgraph)
graphs. You declare a workflow as a tree of constructs; the platform handles compilation,
execution, state management, container lifecycle, and observability.

> **Status: alpha.** The platform foundation is in active development. APIs may change.
> License: _to be decided_ — see [LICENSE](LICENSE).

## Why Agent Foundry

Agentic systems share a large body of infrastructure — container lifecycle, protocol
handling, structured output, lockdown, compilation, state flow, recovery. Rebuilding it
per product is wasteful and error-prone. Agent Foundry centralizes that machinery so
building a new agentic system means *composing constructs and declaring agent behavior*,
not reimplementing infrastructure. The things you change most often — prompts,
instructions, schemas, executors — are callable fields on a construct, so trying a
variation is a one-line change in a declaration.

## Core concepts

A workflow is a **tree of constructs**, composed by direct object reference:

**Control-flow constructs** structure the graph:
- **Sequence** — linear execution of steps
- **Loop** — iterate over a collection
- **Retry** — repeat until a condition is met or attempts are exhausted
- **Conditional** — branch on state

**Action constructs** do work at the leaves:
- **FunctionAction** — in-process function call
- **GateAction** — block for human interaction, return the response as typed output
- **AgentAction** — run a containerized AI agent

State flows between constructs as typed Pydantic models. Each step declares the input
fields it reads and the output fields it merges back; composite constructs accumulate
state within their subgraph and select which fields leave scope.

## Install

```bash
pip install agent-foundry          # core
pip install agent-foundry[mlflow]  # with the optional MLflow telemetry adapter
```

Requires Python 3.14.

## Quickstart

See **[docs/guides/getting-started.md](docs/guides/getting-started.md)** for defining
state models, composing a construct tree, running a process, and extending the platform with
custom constructs. A complete runnable example (with telemetry wiring) lives in
[`examples/mlflow_demo/`](examples/mlflow_demo/).

## Documentation

| Area | Where |
|------|-------|
| Getting started & guides | [`docs/guides/`](docs/guides/) |
| Vision & motivation | [`docs/vision.md`](docs/vision.md) |
| Architecture & ADRs | [`docs/architecture/`](docs/architecture/) |
| Reference (containers, CLI, layering) | [`docs/reference/`](docs/reference/) |
| Subsystem design docs | [`docs/design/`](docs/design/) |
| Contributing | [`CONTRIBUTING.md`](CONTRIBUTING.md) |

---

## Authentication

Agent containers require exactly one of these environment variables:

**Option 1: OAuth token (Claude Pro/Max subscription)**
```bash
claude setup-token          # generates a long-lived token
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-..."
```

**Option 2: API key (API billing)**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

The `DEFAULT_ENV_ALLOWLIST` in `agent_foundry/agents/lifecycle.py` passes these from the host environment into containers. The entrypoint script validates that exactly one auth method is present and rejects the container if both or neither are set.

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

The helper stamps `type=LifecycleEvent.DOMAIN` (= `"domain"`) itself; products only supply the kind and extra fields. `DOMAIN` is the **escape hatch** that lets a product extend the lifecycle stream with its own vocabulary without needing to modify Agent Foundry's enum. Consumers of the jsonl (e.g., a product-specific summary renderer) filter by `type == "domain"` and route on the `kind` subfield.

Rule of thumb: if the event describes something the platform does (start a container, run a turn, invoke a function), that's a platform event — emitted automatically. If the event describes something the *product* does (commit a change set, escalate to a human, mark a review cycle complete), that's a `DOMAIN` event — the product emits it explicitly.

## MLflow Integration

Agent Foundry can emit OpenTelemetry spans at construct boundaries and bind each process run to an MLflow Run. The integration ships in two pieces:

- **`agent_foundry.telemetry`** (always installed) — vendor-neutral OTel emission. Exports `TelemetryConfig`, `RunDefinition`, `RedactionPolicy`, `RunStats`, `ArtifactSpec`, `build_tracer_provider`, and `emit_span`. The compiler wraps every `AgentAction` execution with `emit_span`, sets `gen_ai.operation.name = "chat"`, and applies any product-supplied redaction.
- **`agent_foundry.mlflow_adapter`** (optional, requires the `[mlflow]` extra) — translates AF span attributes to MLflow's namespace at emit time and binds MLflow Run start/end to the run lifecycle.

### Install

```bash
pip install agent-foundry[mlflow]
```

The bare install excludes MLflow. Importing `agent_foundry.mlflow_adapter` without the extra raises an actionable `ImportError` pointing at this command.

### Wire it up in your product

Two sides of the integration share an experiment but configure separately because they target different APIs:

- **Trace spans** flow over OTLP/HTTP. Routing to a specific MLflow experiment uses the `x-mlflow-experiment-id` header on `TelemetryConfig.otlp_headers`. The runner builds the OTLP exporter with these headers when you call `run_process(..., telemetry=config)`, so set them before the run starts.
- **Run data** (params, metrics, tags, artifacts via `mlflow.log_*`) uses the `mlflow` client library's global state. `enable()` sets that state for you when you pass `tracking_uri` and `experiment_id`.

```python
import os

from agent_foundry.mlflow_adapter import MLFLOW_TRANSLATIONS, enable as enable_mlflow_adapter
from agent_foundry.orchestration.runner import run_process
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


def attach_mlflow(event) -> None:
    enable_mlflow_adapter(
        config=config,
        run_context=event.run_context,
        input_model=plan_input,
        tracking_uri=MLFLOW_BASE_URL,
        experiment_id=EXPERIMENT_ID,
    )


await run_process(
    process,
    initial_state=plan_input,
    artifacts_dir=artifacts_dir,
    workspace_volume=workspace_volume,
    base_image_tag=base_image_tag,
    responder_provider=responder_provider,
    telemetry=config,
    on_run_starting=[attach_mlflow],
)
```

`on_run_starting` hooks receive a `RunStartingEvent` (carrying the active
`RunContext`); `on_run_ended` hooks receive a `RunEndedEvent` carrying the
context, the captured exception (or `None` on success), and the run's
final output model (or `None` on failure). Read fields by name —
`event.run_context`, `event.exception`, `event.output` — so meanings are
never ambiguous.

### Setting the experiment ID

Pick one source of truth (env var, config file, hardcoded) and reference it in two places:

1. `TelemetryConfig.otlp_headers["x-mlflow-experiment-id"]` — for trace routing.
2. `enable(..., experiment_id=...)` — for `mlflow.start_run` / `log_params` / `log_metrics`.

If you skip the `tracking_uri` and `experiment_id` kwargs to `enable()`, the MLflow client falls back to its standard env vars (`MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT_ID`). The OTLP header is always required for trace routing — there is no env var fallback for that side.

### Turning telemetry on and off

`telemetry` is an opt-in parameter on `run_process`. Pass `None` (or omit) and AF emits no spans, builds no provider, and never imports MLflow. Pass a `TelemetryConfig` and AF builds a per-run `TracerProvider`, anchors it on `RunContext.telemetry_provider`, runs the process with span emission active, and shuts the provider down on exit. Per-run isolation: the runner never calls `trace.set_tracer_provider`, so concurrent runs in the same process never overwrite each other's providers.

The MLflow adapter is independent — call `enable_mlflow_adapter` from an `on_run_starting` hook only when you want MLflow Run binding. Span emission works without the adapter (you just don't get a wrapping MLflow Run with params/metrics/artifacts).

### Local verification demo

A working end-to-end example lives at `examples/mlflow_demo/`. It includes a `docker-compose.yaml` that brings up a local MLflow 3.7 server with SQLite persistence, a `main.py` showing the wiring above, and a smoke test (`tests/agent_foundry/mlflow_adapter/test_verification_demo.py`, gated by `AF_LIVE_MLFLOW=1`). See `examples/mlflow_demo/README.md` for setup steps.

## License

To be decided. See [LICENSE](LICENSE).
