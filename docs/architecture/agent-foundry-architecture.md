# Agent Foundry Architecture: Current State

This document describes the **as-built** architecture of Agent Foundry — the
load-bearing structural decisions that exist in code today — and marks, with
explicit placeholders and open questions, everything the
[ontology](agent-foundry-ontology.md) calls for that is not yet realized.

It is paired with [agent-foundry-open-decisions.md](agent-foundry-open-decisions.md),
a concise checklist of what still needs to be decided. The details behind each
item in that checklist live here.

## What "architecture" means here

Architecture is the set of structural commitments that are expensive to reverse
and that everything else must conform to: the parts, the boundaries between
them, the invariants that always hold, and the seams through which products
extend the platform. Design — the concrete realization of any one part — is out
of scope for this document except where a design choice has hardened into an
architectural constraint.

## Executive summary

The **bottom of the stack is mature and matches the stated principles**;
the **top of the stack is ontology without code**.

- Solidly architected: `Construct`, the compiler, the validator, and the `Run`
  layer (`RunContext` / `run_process` / `RunOutcome`).
- Largely unrealized: `System`, `Topology` (as a swappable concept), `Role`,
  unbounded/standing-process lifespan, process versioning, run durability, the
  trigger model, and a curated public API surface.

The current implementation is best described as a **mature, bounded
process-graph executor** that the ontology aspires to generalize into a
**system platform**.

---

## Part 1 — The realized architecture

### 1.1 Layered model, as built

```
System      ── NOT REALIZED (no type, no catalog, no shared-resource owner)
  └─ Process       constructs/process.py — thin wrapper over a root Construct
       ├─ Topology      NOT REALIZED as a concept — graph is hardwired
       └─ Construct     constructs/models.py — mature: Construct[I, O] + 8 types
  └─ Run        orchestration/ — mature: RunContext, run_process, RunOutcome
                (bounded / one-shot only)
```

### 1.2 Construct — the composable unit (mature)

- `Construct[I, O](BaseModel, ABC)` (`constructs/models.py`) parameterizes every
  construct with Pydantic input/output state models. Parameterization is
  enforced at construction (`_require_parameterization`); type args are read at
  runtime via `get_type_args`.
- The single recursion seam is `child_specs() -> list[tuple[Construct, str]]`,
  returning each child paired with a local compile-prefix suffix. Walk,
  validate, and compile all recurse through this one method.
- Concrete constructs:
  - **Control-flow:** `Sequence`, `Loop`, `Retry`, `Conditional`.
  - **Action (leaves):** `FunctionAction`, `AsyncFunctionAction`, `GateAction`,
    `AgentAction`, `AICall`.
- Composition is by **direct object reference**. Cross-references (where needed,
  e.g. the container registry) use `id(construct)`, never string names. This is
  the "constructs are a tree, not a graph" principle, realized structurally.

### 1.3 Compiler — typed graph translation (mature)

- `compile_process(process)` (`compiler/compiler.py`) is the translation entry
  point: validate → derive a `TypedDict(total=False)` state schema from the
  union of root I/O fields → recursively compile via `_compile_node` → hand the
  assembled `StateGraph` to LangGraph's `compile()`.
- **Registry-based dispatch.** `_compiler_registry: dict[type[Construct], ...]`
  with `register_compiler`. `_compile_node` walks the type's MRO to find a
  registered compiler (so parameterized generics resolve to their base type),
  and **raises on unknown types** — no silent fallback. Each construct type
  registers its own compiler at import.
- **Typed boundary enforcement.** `_scope_in` / `_scope_out` /
  `_validate_scoped_input` project accumulated state down to a construct's
  declared fields and validate against the Pydantic model, embedding `node_id`
  in failures. This is where the "enforcement at the boundary" principle lives.
- **Accumulated state.** Subgraph state types are built from the union of *all*
  step I/O fields (`_state_type_with_retry_channels`), so intermediate fields
  survive between steps; the composite's declared output type selects what
  leaves scope. "State grows, never shrinks within a subgraph" is realized.
- **Engine hiding.** The compiled object is opaque and documented as
  not-for-direct-use; LangGraph is an encapsulated implementation detail at the
  *run* boundary.

> ⚠️ **Internal exception to strict typing — see Open Question OQ-ENF-1.**
> Inside the compiler, state flows as `dict[str, Any]`, and `Retry` writes
> fixed *string* channels (`"disposition"`, `"exhaustion_reason"`,
> `"attempt_failures"`, plus prefix-namespaced routing keys). The code notes
> this is correct *only* because execution is strictly sequential today; it has
> a documented collision hazard under nesting/concurrency.

### 1.4 Validator — graph-level type compatibility (mature)

- `validate_construct(prim)` (`constructs/validators.py`) mirrors the compiler:
  registry keyed by construct type (`register_validator`), MRO walk,
  **`UnregisteredConstructError` on unknown types**, recursion via
  `child_specs`.
- Checks are local and exact: type identity (`is`, never `issubclass`), field
  availability against accumulated state, and per-construct rules (e.g. Retry
  body in/out identity; Conditional branch contracts; GateAction `prompt_key`
  membership).

### 1.5 Run — execution instance (mature, but bounded only)

- `run_process(...)` (`orchestration/runner.py`) is the **single public entry
  point** for execution. It bootstraps the artifacts dir, builds the
  `JsonlLifecycleWriter` and `AgentContainerRegistry`, constructs `RunContext`,
  installs cooperative SIGINT/SIGTERM handlers, sets the `current_run_context`
  ContextVar, fires `on_run_starting` hooks, invokes the compiled graph once via
  `ainvoke`, and returns exactly one `RunOutcome`.
- `RunContext` (`orchestration/run_context.py`) is a frozen Pydantic model
  carrying run-scoped state: `run_id`, `artifacts_dir`, container registry,
  responder provider, lifecycle writer, cancel event, env, telemetry
  config/provider, and the run hooks. It is exposed to compiled nodes and
  product code via the `current_run_context` ContextVar and the
  `agent_foundry.runtime` accessors (`emit`, `run_id`, `artifacts_dir`,
  `cancelled`, `responder`).
- `RunOutcome` (`orchestration/run_outcome.py`) is a discriminated union —
  `RunCompleted` / `RunAborted` / `RunFailed(BACKSTOP|CRASH)`. The runner never
  re-raises an in-graph exception; it classifies it. Terminal lifecycle events
  and `on_run_ended` hooks fire in a documented order.
- **Per-run isolation.** Each run builds its own OTel `TracerProvider` anchored
  on its `RunContext`; no process-global tracer state is touched. This makes
  concurrent *runs* in one process safe (concurrent *constructs within a run*
  are a separate matter — OQ-ENF-1).

### 1.6 Participant seam (partial) and Role (absent)

- **Participant** has a real seam: `AgentAction.executor` is a required,
  product-chosen callable with contract
  `executor(*, construct, prompt, instructions, run_ctx) -> O | Awaitable[O]`.
  The compiler detects sync vs. async and wires accordingly; it does not care
  what the executor is. The default is `run_agent_in_container` (Docker + Claude
  Code CLI). Model-backed participants have a parallel seam: `InferenceProvider`
  (ABC) behind `AICall`.
- **Role does not exist as a type** — see Placeholder §2.3.

### 1.7 Cross-cutting infrastructure (realized)

- **Lifecycle events.** `LifecycleEvent` (StrEnum, wire-stable) written as
  append-only JSONL via the `LifecycleWriter` ABC (`JsonlLifecycleWriter` /
  `NoOpLifecycleWriter`). Product events go through `runtime.emit` as
  `type="domain"` records. `render_summary` derives `summary.txt`.
- **Telemetry.** OpenTelemetry-based (`telemetry/`), per-run provider isolation,
  vendor-neutral attribute names with a translation seam. Optional MLflow
  integration (`mlflow_adapter/`) attaches purely through the
  `on_run_starting` / `on_run_ended` hooks — pluggable and optional.
- **Agent container model.** `ContainerManagerBase` / `ContainerHandleBase`
  ABCs (single Docker implementation today; podman/k8s anticipated), injected
  into `AgentContainerRegistry` (one container per `AgentAction` per run, keyed
  by `id(construct)`). Structured output is enforced via the
  `AgentTurnEnvelope[O]` discriminated union and schema transformation for the
  Claude Code CLI.
- **Safe-by-default for agents.** `gids=[]` and `mcp_servers={}` by default;
  `cap_drop=['ALL']` with a minimal `cap_add`; a 5-entry env allowlist;
  GID-based filesystem grants; entrypoint lockdown of hidden/read-only dirs.
  Semantic-weight fields (`executor`, `reuse_policy`, `model`) are
  required-with-no-default.

### 1.8 Extension seams summary

| Seam | Mechanism | Status |
|---|---|---|
| New construct type | `register_compiler` + `register_validator` | Realized |
| Agent participant | `AgentAction.executor` callable | Realized (container default) |
| Model provider | `InferenceProvider` ABC + model registry | Realized |
| Container backend | `ContainerManagerBase` ABC | Realized (Docker only) |
| Run integrations | `on_run_starting` / `on_run_ended` hooks | Realized |
| Responder (human-in-loop) | `Responder` ABC + `ResponderProvider` | Realized |
| Topology | — | **No seam (OQ-TOP-1)** |
| Role | — | **No type (§2.3)** |
| Shared resources | — | **No seam (OQ-SYS-2)** |

---

## Part 2 — Placeholders for the unrealized architecture

Each section below names a concept the ontology requires, states what exists
today (usually nothing), and lists the open questions that must be answered
before it can be designed. These are intentionally specifications-to-be, not
designs.

### 2.1 System — the deployment layer

**Ontology role:** the unit of deployment; offers a catalog of processes; owns
versioning and cross-cutting shared resources (knowledge stores, auth,
resources, triggers).

**Today:** no `System` type exists. There is no process catalog, no versioning,
and no owner for shared resources. The registries that exist
(`AgentContainerRegistry`, evals' `AICallRegistry`) are narrower and run- or
subsystem-scoped.

**Open questions**
- **OQ-SYS-1 (catalog & identity):** Is `System` a runtime object, a
  declaration, or both? How does it enumerate the processes it offers, and how
  are processes identified and versioned within it?
- **OQ-SYS-2 (shared resources):** What is the typed seam by which a construct
  reaches a System-owned resource (knowledge store, shared credential, external
  service handle)? `RunContext` carries env/responder/registry today but nothing
  resource-shaped.
- **OQ-SYS-3 (boundary to Run):** A run "selects a process" from a system. What
  does selection look like, and what does the system contribute to a
  `RunContext` at run start?

### 2.2 Topology — structural paradigm

**Ontology role:** the structural paradigm by which a process's constructs
coordinate; graph today, but router/blackboard/etc. anticipated. Topology is a
property of a process and must not leak the engine.

**Today:** graph is hardwired. `compile_process` always builds a LangGraph
`StateGraph`. There is no `Topology` type and no seam below the process where an
alternative coordination model could plug in. Engine-hiding exists at the run
boundary; topology-vs-engine are currently conflated.

**Open questions**
- **OQ-TOP-1 (the seam):** Where does topology become a choice? Is it a field on
  `Process`, a strategy object, or a registry of compilers keyed by topology?
- **OQ-TOP-2 (contract invariance):** The ontology requires a process's identity
  and contract to be independent of its topology. What is the topology-agnostic
  contract that all topologies must honor (entry point, typed I/O, state model)?
- **OQ-TOP-3 (engine boundary):** Does each topology own its own engine, or do
  multiple topologies compile to the same engine? What stays hidden?

### 2.3 Role — the participant contract

**Ontology role:** a pure contract (purpose, scope, input/output schema,
permissions, quality controls) that a participant fulfills inside an action
construct.

**Today:** no `Role` type. The role contract is implicit, scattered across
`AgentAction` fields (`instructions_provider`, `gids`, `mcp_servers`,
`timeout_seconds`, `model`, `effort`, `cwd`). The participant seam (`executor`)
exists, but a role cannot be declared once and bound to different participants.

**Open questions**
- **OQ-ROLE-1 (extraction):** Should Role become a first-class type that
  `AgentAction` (and future action constructs) reference, separating "what must
  be done" from "who/how"?
- **OQ-ROLE-2 (portability):** Can one role be fulfilled by multiple participant
  kinds (container agent, SDK agent, API call, human)? What part of the contract
  is participant-agnostic vs. participant-specific?
- **OQ-ROLE-3 (permissions/scope):** Today scope/permissions live on
  `AgentAction` as `gids`/`mcp_servers`. Do these belong on the Role instead, so
  the safe-by-default story is expressed once per role?
- **OQ-ROLE-4 (authority model):** Role is the natural home for a participant's
  full *authority envelope* — the declarative grant of what it may touch:
  filesystem paths, tools/MCP, **network egress destinations**, and secrets,
  deny-by-default. The substrate already enforces fragments of this (`gids`,
  `cap_drop`, lockdown, MCP allowlist); the gap is a single declarative authority
  model on the Role, enforced at the participant boundary. The *semantic* slice
  of scope (e.g. "a test-writer role must not edit implementation") is not
  substrate-enforceable and routes to a verification gate, not the authority model
  (see value-lever-exploration.md, Candidate 1). This absorbs the
  scope/authority portion of the dropped Candidate 4.

### 2.4 Process lifespan — bounded vs. standing

**Ontology role:** processes are lifespan-agnostic; a process may be a bounded
job or an indefinite standing behavior.

**Today:** bounded only. `run_process` is one `ainvoke` → one `RunOutcome`.
There is no standing loop, no trigger-driven re-entry, and no `lifespan` field
on `Process`.

**Open questions**
- **OQ-LIFE-1 (representation):** Is an unbounded process a distinct topology, a
  `Process` flag, or an outer driver around the bounded executor?
- **OQ-LIFE-2 (state over time):** A standing process accumulates state across
  triggers/cycles. Where does that state live, and how does it relate to the
  per-run accumulated state model? (Couples to OQ-DUR-1.)

### 2.5 Run durability & recovery

**Ontology/CLAUDE.md role:** recovery is named as platform-centralized
infrastructure.

**Today:** `GateAction` uses an in-memory `MemorySaver` checkpointer, so a run
cannot survive a process restart, and there is no resume-from-persisted-state
path. This is acceptable for bounded in-process runs but blocks standing
processes (§2.4) and long-lived gated runs.

**Open questions**
- **OQ-DUR-1 (persistence):** What is persisted, when, and where — full
  accumulated state, lifecycle stream only, or a checkpoint abstraction? Does
  the platform own a durable checkpointer seam?
- **OQ-DUR-2 (resume):** What is the public resume entry point, and how does it
  relate to `run_process`?

### 2.6 Trigger / entry model

**Ontology role:** runs are triggered by an API call, an application, or the
CLI.

**Today:** `run_process` is the only entry, and nothing in the platform calls
it. The sole HTTP surface (`evals/api`) serves evals, not process runs. How a
System exposes its catalog to triggers is undecided.

**Open questions**
- **OQ-TRIG-1 (surface):** Does the platform ship a process-run API/CLI, or is
  triggering a product responsibility on top of `run_process`?
- **OQ-TRIG-2 (catalog binding):** How does a trigger name the process it starts
  (couples to OQ-SYS-1)?

### 2.7 Process versioning & outcome grading

**CLAUDE.md role:** the declaration is the unit being versioned and graded;
naming/versioning configurations and attaching outcome grades to a run is the
payoff of the declarative design.

**Today:** no identity or version on `Process`; no grade attached to a
`RunOutcome`. The data structures exist to support this, but the capability
does not.

**Open questions**
- **OQ-VER-1 (identity):** What identifies a process/agent configuration version
  — a content hash of the declaration, an explicit name+version, or a registry
  entry (couples to OQ-SYS-1)?
- **OQ-VER-2 (grading):** Where does an outcome grade attach, and what is its
  type? How does it relate to `RunOutcome` and the evals subsystem?

### 2.8 Containment & resource governance (table-stakes)

**Provenance:** considered as value lever **Candidate 4** (loss of control /
runtime containment) in `value-lever-exploration.md`, and **dropped as a lever** —
the problem (bounding an untrusted process) is not novel to agents, and the
solution is mechanical (commodity sandboxing / budgeting). It is retained **here**
as table-stakes: capabilities AF must have to run untrusted agents credibly, whose
*absence* is disqualifying but whose presence wins no differentiation. Its one
non-mechanical piece — semantic per-action policy — was routed to verification
(Candidate 1), and its authority/scope piece to Role (§2.3, OQ-ROLE-4).

**Today:** partial. The substrate provides `cap_drop`, filesystem lockdown
(hidden/read-only dirs + GID), an MCP allowlist, a 5-entry env allowlist,
`timeout_seconds`, cooperative `cancel_event`, and `RunOutcome` failure
classification. Missing: network egress control, enforced cost/turn/token
budgets, forced (non-cooperative) termination, and failure routing/recovery
instead of hard abort.

**Open questions**
- **OQ-GOV-1 (egress):** Does AF enforce a per-run/per-role network egress
  allowlist at the container boundary (exfiltration / SSRF / unapproved calls)?
  (Couples to OQ-ROLE-4.)
- **OQ-GOV-2 (budgets):** Where are token/cost/turn/time budgets declared, and
  what does the platform do on breach — abort, escalate, or pause?
- **OQ-GOV-3 (forced termination):** When an agent ignores cooperative
  cancellation, does the platform guarantee termination by killing the container —
  and how does that reconcile with graceful (cooperative) stop?
- **OQ-GOV-4 (recovery vs. crash):** On a recoverable failure (e.g. role-boundary
  refusal), does the run route/escalate/checkpoint instead of aborting? (Couples
  to OQ-DUR-1 and the §2.5 recovery story.)

### 2.9 Participant breadth beyond the current four

**Ontology role:** participants include external services, communication
channels, and ML models, not just agents/model-calls/functions/humans.

**Today:** `FunctionAction`, `AsyncFunctionAction`, `GateAction`,
`AgentAction`, `AICall` exist. `ServiceAction` and similar are named as future
in CLAUDE.md. The executor/provider seams could host them, but without a Role
type (§2.3) each new participant kind re-implements the contract ad hoc.

**Open question**
- **OQ-PART-1:** Which participant kinds are in scope, and do they arrive as new
  action constructs, new executors behind existing constructs, or roles bound to
  generic participants? (Couples to OQ-ROLE-1.)

### 2.10 Public API surface

**Today:** `src/agent_foundry/__init__.py` is empty. Products import from deep
internal module paths, so there is no declared, stable surface and no boundary
between platform API and platform internals.

**Open question**
- **OQ-API-1:** What is the curated public API (the facade products are allowed
  to depend on), and what is explicitly internal?

---

## Part 3 — Standing enforcement gaps

These are stated invariants that nothing currently guards. They are not new
features; they are missing guardrails on the realized architecture.

- **OQ-ENF-1 (typed internal state):** The "no string-keyed dicts / no untyped
  smuggling through state" principle stops at the construct boundary. Inside the
  compiler, `Retry`'s fixed string channels are correct only under strictly
  sequential execution, with a documented collision hazard under nesting or
  concurrency. Decision needed: enforce a typed internal-state contract, or
  formally constrain what may run concurrently.
- **OQ-ENF-2 (concurrency invariant):** Concurrent *runs* are isolated;
  concurrent *constructs within a run* are not (see OQ-ENF-1). There is no check
  preventing a future parallel construct from silently violating this. Decision
  needed: make the sequential-execution assumption an enforced invariant or
  remove the dependency on it.
- **OQ-ENF-3 (construct-name uniqueness):** `AgentAction.name` collisions
  silently clash in artifact paths and logs; documented, unenforced. Decision
  needed: enforce uniqueness at validation, or remove the dependence on name
  uniqueness.

---

## Part 4 — Repository hygiene notes (non-architectural)

These do not bear on the architecture but signal in-flight moves a reader will
encounter:

- `src/agent_foundry/observability/` is an empty directory shadowing the live
  `telemetry/` package — likely an abandoned or planned rename. Resolve or
  remove.
- `src/agent_foundry/agents/docker_v2/` is a "codex-cohabit" experiment wired to
  nothing in `src/`. Either promote behind the `ContainerManagerBase` /
  executor seams or remove.
- The `Construct` / `Process` names are recent renames (from `Primitive` /
  `Plan`); ensure no stale references remain outside `docs/`.
