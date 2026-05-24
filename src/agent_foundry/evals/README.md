# Agent Foundry Evals

A typed, declarative eval system for the primitives Agent Foundry
defines. Products built on Agent Foundry
use this package to score the behavior of their AI calls and agents
against curated datasets.

The package provides:

- **Declarative suite types** — `EvalSuite`, `Case`, `Dataset`,
  `Evaluator` specs, `RunResult` — pure agent-foundry Pydantic models.
  Suite files in your app are Python data, not framework calls.
- **Two target kinds** — `AICallTarget` evaluates an `AICall` (one
  inference call producing structured output) via direct invocation;
  `AgentTarget` evaluates an `AgentAction` (multi-turn containerized
  agent) through the full orchestration path.
- **Pluggable runner backends** — execution goes through the `Runner`
  Protocol. The default backend wraps Pydantic-Evals; alternative
  backends (DeepEval, Inspect, custom) can be added by dropping a new
  file under `runners/`.
- **App-side registry** — `AICallRegistry` is the opt-in surface for
  exposing AICalls to the eval system (today consumed by the API
  server; future consumers include the web app).
- **CLI and HTTP API** — `pdm eval` runs a suite file; `pdm eval-api`
  boots a FastAPI server that exposes registered AICalls as
  evaluation targets.
- **Persistent reports** — each run is written as a self-describing
  JSON document, ready for downstream viewers.

## Architecture: framework-agnostic by construction

The eval system treats the third-party execution engine
(Pydantic-Evals today, possibly others tomorrow) as **infrastructure**,
not data model. Agent-foundry owns every type that crosses a public
or persistent boundary; backends translate to and from their own
representations only at the moment of execution.

The runtime contract is the `Runner` Protocol (`models/runner.py`).
Concrete runners live in `runners/` and are the only modules in
agent-foundry that may import third-party eval libraries. Callers
resolve a runner at startup via `runner_loader.load_runner(spec)`,
which takes a `module:Class` string and instantiates dynamically — no
caller statically depends on any specific backend.

What this buys:

- **Swap eval frameworks** by writing one new file in `runners/`.
  Models, API, registry, suite files, and downstream consumers don't
  change.
- **Multi-runner coexistence** — AICall evals could route to one
  backend, agent-system evals to another, all behind one declarative
  surface.
- **Serializable suite specs** — every model is pure Pydantic, so
  suites round-trip through JSON cleanly. The future web app
  persists suite definitions in a database and rehydrates via
  `model_validate`; the models *are* the spec.
- **Light import graph by default** — the API server, the registry,
  and any caller that only inspects metadata never load the heavy
  eval framework. Memory cost is paid once, in the runner process,
  when an eval actually runs.

```
src/agent_foundry/evals/
├── __init__.py
│
├── models/                      ← declarative contracts (pure Pydantic)
│   ├── __init__.py              ← re-exports
│   ├── targets.py               ← EvalTarget, AgentTarget, AICallTarget, EvalTargetKind
│   ├── cases.py                 ← Case, Dataset
│   ├── evaluators.py            ← Evaluator base + IsInstance, EqualsExpected, LLMJudge specs
│   ├── suite.py                 ← EvalSuite
│   ├── report.py                ← RunResult and report types
│   └── runner.py                ← Runner Protocol
│
├── registry.py                  ← AICallRegistry (app-side opt-in surface)
├── persistence.py               ← JSON read/write of RunResult
├── responder.py                 ← RaiseOnInvokeResponder (agent-target eval path)
├── tasks.py                     ← build_run_primitive_plan_task, build_invoke_ai_call_task
├── cli.py                       ← command-line entry
├── runner_loader.py             ← resolves a runner module:Class spec to an instance
│
├── runners/                     ← execution backends
│   ├── __init__.py
│   └── pydantic_evals.py        ← PydanticEvalsRunner (initial implementation)
│
└── api/                         ← HTTP surface
    ├── __init__.py
    ├── __main__.py              ← bootstrap: load config → load registry → build app → uvicorn.run
    ├── app.py                   ← create_app(registry)
    ├── config.py                ← TOML loader for agent_foundry.config
    ├── registry_loader.py       ← resolves the registry module:VAR spec
    ├── schemas.py               ← TargetSpec
    └── targets.py               ← /targets routes
```

## Using the eval system

### 1. Configure

Place an `agent_foundry.config` (TOML) at your app's repo root:

```toml
registry = "your_app.evals.registration:EVAL_REGISTRY"

[api]
host = "127.0.0.1"
port = 8000
```

The `registry` value is a `module:attribute` string pointing at your
app's `AICallRegistry` instance.

### 2. Register evaluable AICalls

In your app, instantiate an `AICallRegistry` and register each AICall
you want exposed to the eval system:

```python
# your_app/evals/registration.py
from agent_foundry.evals.registry import AICallRegistry
from your_app.ai_calls import design_review, work_router

EVAL_REGISTRY = AICallRegistry()
EVAL_REGISTRY.register("design_review", design_review)
EVAL_REGISTRY.register("work_router", work_router)
```

Apps choose which AICalls to expose. Unregistered AICalls are
invisible to the eval system.

### 3. Define a suite

A suite is a Python file that exports a `suite: EvalSuite`:

```python
from agent_foundry.evals.models import (
    AICallTarget, Case, Dataset, EqualsExpectedSpec, EvalSuite,
)
from your_app.ai_calls import design_review

suite = EvalSuite(
    name="design_review_v1",
    target=AICallTarget(ai_call=design_review),
    dataset=Dataset(
        name="design_review_cases_v1",
        cases=[
            Case(name="good", inputs=..., expected_output=...),
            Case(name="bad",  inputs=..., expected_output=...),
        ],
        evaluators=[EqualsExpectedSpec()],
    ),
    invocations_per_case=3,
)
```

### 4. Run

Via CLI, against any suite file:

```bash
pdm run python -m agent_foundry.evals.cli path/to/suite.py \
    --out-dir ./eval-runs
```

Reports are written to `./eval-runs/<run_id>/report.json`.

Via the HTTP API:

```bash
pdm eval-api          # boots the FastAPI server on the configured port
curl http://127.0.0.1:8000/targets
curl http://127.0.0.1:8000/targets/design_review
```

Today the API serves target discovery (`/targets`). The roadmap is to
add a `/runs` endpoint for executing suites over HTTP, then a web app
that uses both endpoints to author suites in a UI, run them, and
browse results — all consuming the same `AICallRegistry` apps already
expose.

## Boundary enforcement

Two mechanisms protect the architecture from drift:

**import-linter contract.** Catches direct API coupling — any module
in agent-foundry importing `pydantic_evals` outside of
`runners.pydantic_evals` fails CI.

```toml
[tool.importlinter]
root_packages = ["agent_foundry"]
include_external_packages = true

[[tool.importlinter.contracts]]
name = "Third-party eval libraries confined to evals.runners"
type = "forbidden"
source_modules = ["agent_foundry"]
forbidden_modules = ["pydantic_evals"]
ignore_imports = [
    "agent_foundry.evals.runners.pydantic_evals -> pydantic_evals",
]
```

`pdm lint-imports` runs on pre-commit and pre-push, so the contract
is checked before every push.

**Runtime meta-path blocker (`tests/conftest.py`).** Catches
transitive loads — installs a `sys.meta_path` finder that raises
`ImportError` if anything during a `tests/` worker's lifetime
attempts to import `pydantic_evals`. Fires for both static-import
chains caught at collection time and dynamic loads during test
execution. The error surfaces as a normal test failure (propagates
cleanly under xdist).

**Test directory split.** Tests that exercise the runner backend (and
therefore load the heavy library) live under `tests-evals/` and run
via `pdm test-evals`. The main `tests/` tree is guarded by the
meta-path blocker: any test added there that triggers a heavy load
fails immediately, telling the author to move it to `tests-evals/`.
This keeps the 16 xdist workers in `pdm test-unit` free of the
per-worker memory cost of the eval framework.
