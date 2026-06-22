# Eval Harness for Agent Foundry Agents

**Date:** 2026-05-12
**Status:** Design approved, not yet implemented

## Goal

Provide a harness for evaluating a single `AgentAction`'s behavior against a
curated suite of inputs with expected outputs. Support code-based validators
out of the box and LLM-judge validators for subjective criteria. Enable
fast iteration on agent design (instructions, model, etc.) by making it
cheap to re-run the suite against a modified declaration.

## Scope

**In scope (v1):**

- Single-agent evaluation: pick one `AgentAction`, run it against a suite of cases.
- Multiple invocations per case (handles LLM nondeterminism via repeat-and-aggregate).
- Code validators and LLM-judge validators.
- Dedicated CLI; runner-as-library so a future UI can consume the same APIs.
- Persistent JSON reports for cross-run comparison.

**Out of scope (v1, deferred):**

- First-class variant support (comparing multiple declarations in one run). The
  external-loop pattern below covers this for v1; framework support is added
  later if/when the pattern proves insufficient.
- Agent-side cost / token / cache-hit reporting.
- Cross-run diffing tooling.
- Web/TUI viewer.
- Trace replay against a recorded production run.

## Foundational decisions

### Adopt Pydantic Evals as the eval engine

Use [pydantic-evals](https://pydantic.dev/docs/ai/evals/) as the core. We do not
roll our own `Case`, `Dataset`, `Evaluator`, or `EvaluationReport` types.

Reasons:

- Their Case / Evaluator / Report primitives match what we'd build.
- `LLMJudge` is a built-in evaluator — saves us writing one.
- Built-ins for the common code checks: `EqualsExpected`, `Equals`, `Contains`,
  `IsInstance`, `MaxDuration`.
- Typed Pydantic models throughout, which aligns with Agent Foundry's
  "strict typing at boundaries" principle.
- Logfire integration is opt-in; we do not enable it.

Verified during design:

- `pdm add pydantic-evals` resolves cleanly with no conflicts against the
  current dependency tree (`langgraph`, `langchain`, `anthropic`, `pydantic`).
- 6 transitive packages added, including `pydantic-ai-slim` (used internally by
  `LLMJudge`) and `logfire-api` (no-op shim, dormant unless full `logfire`
  package installed).
- End-to-end smoke test passed.

**Caveat:** "slim" is a misnomer at import time — importing `pydantic_evals`
eagerly loads ~89 `pydantic_ai` modules. One-time memory cost, fine for a
dev CLI. Production agent runs are unaffected (they don't import `pydantic_evals`).

### Platform code is untouched

The harness consumes Agent Foundry's existing public APIs. No refactors required.

- Invocation uses the existing `run_primitive_plan` orchestration entry point.
  The harness wraps the AgentAction under test in a `PrimitivePlan(root=agent)`,
  passes the case's typed input as `initial_state`, and gets the typed output.
- `RunContext` is constructed by `run_primitive_plan`; the harness supplies its
  constructor args (artifacts dir, workspace volume, base image tag,
  responder provider).
- A `RaiseOnInvokeResponder(Responder)` is the only new collaborator the
  harness contributes — a single-agent eval should not trigger responder
  interactions, and if it does the eval fails loudly rather than silently
  auto-answering.

## Architecture

### Layering

```
┌─────────────────────────────────────────────┐
│ CLI (thin wrapper)                          │  pdm eval <path>
│   parse args → load suite → run → render    │
└──────────────────┬──────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│ Runner (library)                            │  agent_foundry.evals.runner
│   run_suite(suite) → RunResult              │
└──────────────────┬──────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│ Pydantic Evals                              │  Dataset, Case, Evaluator,
│   dataset.evaluate(task) → EvaluationReport │  LLMJudge, EvaluationReport
└──────────────────┬──────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│ Agent Foundry orchestration                 │  run_primitive_plan
│   PrimitivePlan(root=agent) →               │
│     RunContext → executor → typed output    │
└─────────────────────────────────────────────┘
```

- **Runner-as-library, CLI-as-thin-wrapper.** A future UI consumes `run_suite`
  directly or reads persisted `report.json` files.
- **Persistence is the UI contract.** As long as runs persist a self-describing
  JSON, any viewer can render across runs.

### Core types

```python
class EvalSuite(BaseModel):
    name: str
    agent: AgentAction
    dataset: Dataset            # pydantic_evals.Dataset
    invocations_per_case: int

class RunResult(BaseModel):
    run_id: str
    suite_name: str
    started_at: datetime
    ended_at: datetime
    invocations_per_case: int
    report: EvaluationReport    # contains (cases x N) entries
```

The `EvaluationReport` is stored verbatim. Per-case aggregation across
the N invocations is recovered via `report.case_groups()`.

### N-repeat orchestration

Pydantic Evals' `Dataset.evaluate(task, repeat=N)` natively expands each
case into N entries (named ``"<case> [i/N]"``) and runs them in a single
concurrent batch (subject to ``max_concurrency``). The runner calls
``evaluate`` once and returns the single resulting report. Earlier design
sketches proposed an outer Python loop; that was redundant — ``repeat``
already does it, and the native expansion is more efficient because
all ``(case, invocation)`` pairs are scheduled in one concurrency window.

### Variants

Not part of v1's framework. Users get variants by looping in their suite file:

```python
variants = [
    ("baseline", agent_a),
    ("opus",     agent_a.model_copy(update={"model": "claude-opus-4-7"})),
    ("terse",    agent_a.model_copy(update={"instructions_provider": terse})),
]

for name, agent in variants:
    suite = EvalSuite(name=f"agent_a__{name}", agent=agent, dataset=..., invocations_per_case=3)
    run_suite(suite)  # writes its own evals/runs/<run_id>/report.json
```

Each variant produces its own persisted run; cross-variant comparison is a
future "diff two report.json files" tool. Whether framework-level variant
support is worth building is a question revisited after living with this
pattern.

### Responder

```python
class RaiseOnInvokeResponder(Responder):
    async def respond(self, request, context):
        raise RuntimeError(
            "Responder invoked during eval. Single-agent eval cases must not "
            "trigger interactions; the agent must run to completion on its own."
        )
```

Used via `static_provider(RaiseOnInvokeResponder())`. Loud failure beats
auto-answering with non-deterministic outcomes.

## UX

### Defining a suite

Suite source lives at `evals/<suite-name>/suite.py` and exports `suite`:

```python
# evals/agent_a/suite.py
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EqualsExpected
from agent_foundry.evals import EvalSuite
from agent_foundry.archipelago.agents import agent_a, AgentAInput, AgentAOutput

suite = EvalSuite(
    name="agent_a",
    agent=agent_a,
    dataset=Dataset[AgentAInput, AgentAOutput, None](
        name="agent_a_v1",
        cases=[
            Case(name="empty_input", inputs=AgentAInput(...), expected_output=AgentAOutput(...)),
            # ... more cases
        ],
        evaluators=[EqualsExpected()],
    ),
    invocations_per_case=3,
)
```

Python over YAML/JSON: typed Pydantic inputs author best in Python, LSP
navigation works, validators are user-written classes (potentially with
custom logic).

### Running

```
pdm eval evals/agent_a/suite.py
```

Flags (initial set, expand as needed):

- `--out-dir <path>` — override default `evals/runs/` location
- `--invocations <N>` — override `invocations_per_case` for this run
- `--max-concurrency <N>` — pass through to Pydantic Evals

### Console output

At end of run: print the per-case results table from Pydantic Evals'
`EvaluationReport`, aggregated across the N invocations (pass-rate column
per case). Full details written to `report.json`. Easily revised later.

### Persistence

- `evals/<suite-name>/suite.py` — source, checked in.
- `evals/runs/<run_id>/report.json` — per-run result, generated.
- `evals/runs/` is gitignored.
- `run_id` is timestamp-based for natural sort order.

## Validators

### Built-in (from Pydantic Evals)

- `EqualsExpected` — exact match against `case.expected_output`
- `Equals(value=...)` — exact match against a fixed value
- `Contains(value=..., case_sensitive=..., as_strings=...)` — substring/element-of
- `IsInstance(type_name=...)` — type check
- `MaxDuration(seconds=...)` — execution under a time threshold
- `LLMJudge(rubric=..., score=..., assertion=...)` — rubric-based LLM judge

### Custom (Agent Foundry side, as needed)

Agent-Foundry-specific assertions (e.g. "the typed output's `tool_calls`
field includes X") subclass Pydantic Evals' `Evaluator` protocol:

```python
class ToolCallContains(Evaluator[InputT, OutputT, None]):
    expected_tool: str
    async def evaluate(self, ctx: EvaluatorContext) -> bool:
        return any(c.name == self.expected_tool for c in ctx.output.tool_calls)
```

### Error semantics

Pydantic Evals' Evaluator return is rich (bool / float / dict of named
results). For invocations where the *agent* fails (raises) before validation
runs, the runner records the failure as a separate outcome — distinct from
"the agent's output failed validation." This split matters for diagnosing
flaky agents vs. failed assertions.

## What we deliberately don't snapshot

For the case dataset, Pydantic Evals' `Case` model already serializes the
inputs, expected outputs, and metadata cleanly — that's the snapshot.

For the agent, we do not serialize callable fields (`prompt_builder`,
`instructions_provider`, `executor`). The variant name (or suite name) is the
identifier; the declaration's source code is in git. If reproducibility
debugging becomes a real need, we add structured snapshot at that point.

## Open questions deferred to implementation

- CLI flag set beyond the initial three.
- Whether to capture per-invocation resolved prompts/instructions for
  debugging (Pydantic Evals doesn't natively, threading them through
  requires custom hooks).
- Whether to add agent-side metrics (cost, tokens, latency, cache) — if/when
  added, this raises a platform-level question about typed contracts vs.
  telemetry scraping. Punt until needed.
- Whether to add lifecycle hooks (Pydantic Evals supports per-case setup/
  teardown — useful if eval cases need fixtures).

## Implementation outline

A rough sketch, not a binding plan:

1. Add `pydantic-evals` to `pyproject.toml`.
2. Create `agent_foundry/evals/` package:
   - `models.py` — `EvalSuite`, `RunResult`
   - `responder.py` — `RaiseOnInvokeResponder`
   - `runner.py` — `run_suite(suite) -> RunResult`, wraps `run_primitive_plan`
     as the task function, calls `dataset.evaluate` N times
   - `cli.py` — `pdm eval` entrypoint
   - `persistence.py` — write/read `report.json`
3. Add `pdm eval` to `pyproject.toml` scripts.
4. Write a smoke test against a small real `AgentAction` to verify end-to-end.
5. Add `.gitignore` entry for `evals/runs/`.

Tests in `tests/agent_foundry/evals/` cover `run_suite` against an in-process
fake executor, persistence round-trip, and CLI argument parsing.
