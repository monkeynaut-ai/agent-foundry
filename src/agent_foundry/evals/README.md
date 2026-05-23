# Agent Foundry Evals — Design Notes

## The pydantic-evals coupling problem

Agent Foundry currently uses Pydantic-Evals as both the **execution
engine** (`Dataset.evaluate`, async concurrency, evaluator framework,
report assembly) **and** part of its own data model — `EvalSuite`
embeds a `pydantic_evals.Dataset`, `RunResult` embeds a
`pydantic_evals.EvaluationReport`. Any module that touches those
types transitively loads the entire library at import time.

Two consequences fall out of this:

1. **Memory cost multiplied across processes.** Pytest runs with
   `-n 16` xdist workers; each is a separate interpreter that
   loads pydantic-evals independently. Anything in the runtime web
   app that needs even an enum from `evals.models` pulls the
   library into every server worker.
2. **Single-vendor lock-in.** The library isn't just a backend choice
   — it's woven into our public type surface. Replacing it, or
   supporting a second eval framework alongside it, would ripple
   through models, the API server, downstream consumers, and stored
   reports.

## The architecture

Treat pydantic-evals as **execution infrastructure**, not data model.
Three principles:

- **Models layer** owns the declarative contracts: `EvalSuite`,
  `Case`, `Dataset`, `Evaluator`, `RunResult`, and the `Runner`
  Protocol. Pure Pydantic; zero third-party eval-library imports.
- **Runners layer** owns the execution backends. Each file is one
  implementation of the `Runner` Protocol. Third-party eval libraries
  may be imported here, and only here.
- **API and other consumers** depend on the model layer (including
  the `Runner` Protocol) but never statically import a concrete
  runner. Dependency injection at app construction binds a specific
  runner; concrete backends are resolved at startup via dynamic
  `importlib` lookup from a config-declared `module:Class` string —
  the same pattern the registry already uses.

This mirrors the platform's existing pluggable-backend pattern:
`InferenceProvider` isolates inference backends; per-primitive
executors isolate execution mechanisms; the registry isolates app
code from the eval system. Evals follow the same shape.

## Package layout

```
src/agent_foundry/evals/
├── README.md
├── __init__.py
├── __main__.py                  ← bootstrap: loads config → resolves backends → builds app → uvicorn.run
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
├── cli.py                       ← command-line entry
│
├── runners/                     ← execution backends
│   ├── __init__.py
│   └── pydantic_evals.py        ← PydanticEvalsRunner (initial implementation)
│
└── api/                         ← HTTP surface
    ├── __init__.py
    ├── app.py                   ← create_app(registry, runner)
    ├── config.py
    ├── registry_loader.py
    ├── runner_loader.py
    ├── schemas.py
    └── targets.py
```

Each directory boundary signals a contract:

- **Top-level files** (`registry.py`, `persistence.py`, `cli.py`) =
  orthogonal services that consume the model layer only.
- **`models/`** = declarative public API. Stable surface. No
  third-party eval imports.
- **`runners/`** = pluggable backends. New backend = new file. No
  other code in the package may import these directly.
- **`api/`** = HTTP surface. Depends on the model layer + registry.
  Resolves concrete backends dynamically via the loader modules.
- **`__main__.py`** at the package root = the one wiring point.
  Reads config, instantiates registry and runner, builds the app,
  launches uvicorn.

## Boundary enforcement

```toml
# Third-party eval libraries confined to runners/
[[tool.importlinter.contracts]]
source_modules = ["agent_foundry"]
forbidden_modules = ["pydantic_evals", "deepeval", "inspect_ai"]
ignore_imports = ["agent_foundry.evals.runners.*"]

# API surface depends only on declarative types + registry
[[tool.importlinter.contracts]]
source_modules = ["agent_foundry.evals.api"]
forbidden_modules = ["agent_foundry.evals.runners", "agent_foundry.evals.cli"]
```

Future PRs that re-couple the API to a runner implementation, or that
import pydantic-evals outside its designated backend file, fail CI.
The architectural intent becomes a contract the build checks for us.

## What we gain

**Eval-framework agnosticism.** Pydantic-evals becomes one backend
among potentially many. Swap it for DeepEval, Inspect, OpenAI Evals,
LangSmith, or a custom runner by rewriting one module. Models, API
server, registry, suite files, and downstream consumers (Archipelago,
the future eval web app) don't change.

**Multi-runner coexistence.** Different suite kinds can route to
different runners. AICall evaluations might use pydantic-evals for
its structured-output ergonomics; agent-system evaluations might use
something with richer trace tooling; regression suites might use a
deterministic in-house runner. The declarative layer stays uniform.

**Ecosystem resilience.** The Python eval-framework landscape is
volatile — new entrants regularly, abandonment risk on any single
one. Decoupling protects the platform from any one vendor's roadmap.

**First-class serializable specs.** Pure agent-foundry Pydantic
types round-trip through JSON cleanly. The future eval web app
stores suite definitions in a database and rehydrates them via
`model_validate` — no parallel "spec layer" needed. The models
*are* the spec.

**Lightweight import graph by default.** The API server, the
registry, and any caller that only inspects suite metadata never
load pydantic-evals at all. Memory cost is paid once, in the runner
process, at execution time — not by every consumer that happens to
touch a model.

**Lint-enforced boundary.** The architectural intent becomes a
contract the build checks for us, not a discipline we have to
remember.
