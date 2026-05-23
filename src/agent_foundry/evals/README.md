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

- Agent-foundry owns the declarative types: `EvalSuite`, `Case`,
  `Dataset`, `Evaluator`. Pure Pydantic, zero pydantic-evals imports.
- A single `Runner` interface defines "execute this suite, return a
  typed report."
- The default `PydanticEvalsRunner` translates our types to
  pydantic-evals' types, calls `Dataset.evaluate`, translates the
  report back. It is the **only** module that imports pydantic-evals.
- An `import-linter` contract enforces the boundary: nothing outside
  the runner module may import `pydantic_evals`. Future PRs that
  re-couple fail CI.

This mirrors the platform's existing pattern: `InferenceProvider`
isolates inference backends; per-primitive executors isolate
execution mechanisms; the registry isolates app code from the eval
system. Evals would now follow the same shape.

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
