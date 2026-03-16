Analysis of the “agent foundry initial build instructions” document in the context of “Workflow Orchestrator MVP (Control Plane Lite)”

> **Cross-references:** This document analyzes the Agent Foundry build instructions ([`docs/implemented/agent_foundry_initial_build_instructions.md`](../implemented/agent_foundry_initial_build_instructions.md)). For the resulting orchestrator feature spec, see [`implemented/archipelago_workflow_orchestrator_feature_spec.md`](implemented/archipelago_workflow_orchestrator_feature_spec.md). For the platform conceptual model, see [`docs/architecture/agent-foundry-ontology.md`](../architecture/agent-foundry-ontology.md).

## Executive summary
The attached document describes a plan-compiled orchestration platform that closely matches the “Control Plane Lite” requirements: (1) a DAG of agent/tool steps with typed inputs/outputs, (2) a capability registry that defines runnable units and enforces schemas, (3) breakpoint-driven human gates plus checkpoint/resume, and (4) tracing/observability as a core primitive.

The core idea is **Plan → Compiler → Executable Graph**, which is a strong fit for Archipelago’s current stage where agents exist but workflow/control-flow is still manual.

---

## What the document already specifies that directly implements Control Plane Lite

### 1) DAG execution with typed IO
- Nodes/subgraphs are produced from a machine-compilable `GraphWiringPlan` (Pydantic) with explicit nodes/edges and constraints.
- Validation covers referential integrity (unknown capabilities, dangling edges), schema checks, breakpoints, and loop termination rules.

**Control Plane Lite mapping:** Your “DAG of steps with typed IO” can be implemented as a validated plan artifact that is compiled into an executable LangGraph.

### 2) Capability Registry as the stable substrate
- The Capability Registry is the catalog of all runnable “things” (agents, tools, subgraphs), each with input/output schemas and metadata.
- Runtime wrappers enforce schemas and fail fast with typed errors.

**Control Plane Lite mapping:** This gives you the separation you need while agents are in flux: orchestration can remain stable if capability contracts are stable.

### 3) Human-in-the-loop gates as explicit breakpoints
- Breakpoints are first-class plan constructs (interrupt payload + pause + resume).

**Control Plane Lite mapping:** Human approvals become explicit nodes/edges rather than implicit “manual steps,” enabling deterministic replay and auditable gates.

### 4) Checkpoint/resume and determinism hooks
- The compiler slices include checkpoint/resume and determinism guidance (seeded randomness, consistent planning).

**Control Plane Lite mapping:** Your “resume from checkpoint + rerun affected nodes” requirement is explicitly anticipated.

### 5) Observability and evaluation hooks
- Node-level tracing spans and tool/retrieval traces are required.
- The document includes an “eval gate” concept (enforced on paths to terminal state).

**Control Plane Lite mapping:** Inspectability is built in; quality gates can be introduced incrementally.

---

## Why this is a good fit for Archipelago right now
Archipelago’s primary bottleneck is the manual control/data flow between rough-but-working agents. A plan-compiled orchestrator helps because it:
- **Makes workflows explicit** (a plan is a concrete artifact, not tribal knowledge)
- **Reduces brittleness** (schemas + validation catch mismatches early)
- **Improves debuggability** (plans, traces, and artifacts provide structured visibility)
- **Enables safe autonomy ramps** (breakpoints, budgets, and gating)

---

## Suggested mapping of current Archipelago agents into the document’s platform

### Treat each existing stage as a capability
- `strategy.generate_product_brief` → outputs `ProductBrief`
- `architecture.generate_feature_arch` → outputs `FeatureArchitecture`
- `spec.generate_feature_spec` → outputs `FeatureSpec` + `TestPlan`
- `dev.implement_feature_tdd` → outputs `CodeDiff/PR` + `TestResults`

Each becomes a `CapabilitySpec` with strict IO schemas.

### Use `GraphWiringPlan` as the “manual workflow replacement”
A minimal pipeline plan:
1. Strategy node
2. Architecture node
3. Spec node
4. Breakpoint gate: “Spec approval”
5. Dev/Test node
6. Breakpoint gate: “Merge approval” (optional)

Add loops later (spec revise loop; implement-test-fix loop) once basics run reliably.

---

## What’s missing (or needs Archipelago-specific decisions)

### A) Artifact canon and state model
The platform assumes a state object. For Archipelago, define a minimal canonical state early:
- `product_brief`, `feature_architecture`, `feature_spec`
- `test_plan`, `code_patch`, `test_results`
- `release_plan`, `runbook`, `deploy_status` (later)

Then wire persistence/checkpointing to this state.

### B) Planner scope: start deterministic
The document recommends starting with a deterministic/primitive planner that emits valid plans without heavy retrieval. This is aligned with your current needs: make execution repeatable first, then add intelligence.

### C) Template expansion to capture common sub-workflows
Define Archipelago-native templates once the basic compiler works:
- `spec_review_revise_loop`
- `implement_tdd_loop`
- `security_review_gate`
- `deploy_monitor_rollback`

---

## Minimal “Control Plane Lite” slice set (lowest viable scope)
To get a working orchestrator that replaces manual flow, the minimum subset is:
1. Capability Registry + schema enforcement wrappers
2. `GraphWiringPlan` schema + validation
3. Compiler that translates plan → executable graph and runs multi-node flows
4. Tracing spans per node and artifact capture
5. Breakpoints + checkpoint/resume next

Defer retrieval-planner sophistication and advanced gating until after the first end-to-end run works.

---

## Key design implication
This approach makes orchestration **plan-driven and compiled**, not “a manager agent deciding everything at runtime.” For an in-progress system, that is typically safer and easier to debug.

---

## Immediate next concrete deliverable for Archipelago
Produce a v0 “Archipelago Pipeline Plan” and registry for your four agents:
- Define IO schemas for each stage
- Register each stage as a capability
- Write a single `GraphWiringPlan` that chains them with one breakpoint gate
- Compile and execute with full artifact capture

This alone should eliminate most manual routing and create a stable surface for future agent tuning.