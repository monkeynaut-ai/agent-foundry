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

---

## Integrating Claude Code / Codex as a self-contained “implement this feature spec” worker (Docker)

### Core concept
Treat Claude Code (CC) and/or Codex as **external coding capabilities** behind a single stable interface, e.g. `coding.implement_feature_from_spec`.

**Why this fits the current Archipelago workflow:** CC remains a self-contained worker that iterates across the spec’s PRs/commits and performs the red→green TDD loop per commit. The orchestrator manages only the wrapper concerns: lifecycle, safety, observability, and breakpoints.

### Capability interface (recommended)
**Input (typed)**
- `repo_ref`: commit SHA / branch to start from
- `feature_spec`: full spec (PR/commit plan + acceptance criteria)
- `constraints`: budgets (time/cost), allowed commands, network policy
- `test_commands`: definition of “green” (can be embedded per-commit in spec)
- `gates`: optional stop points (e.g., stop after each PR)

**Output (typed)**
- `result_summary`: completed PRs/commits, failures, next steps
- `workspace_ref`: container/workspace identifier + git status
- `patches_or_prs`: diffs and/or created branches/PR handles
- `evidence`: per-commit test logs/summaries (at minimum), plus commands executed

---

## Required primary mode: live session execution (Docker)
This is the default and required execution strategy.

**Goal:** allow CC to pause for clarification/permission without losing session context.

**Execution model**
1. Orchestrator starts a **dedicated Docker container per run** (ephemeral but durable for the duration of the run).
2. Clone/checkout repo inside container; mount only a dedicated workspace volume (no host filesystem mounts beyond that).
3. Launch CC (or Codex) under a **persistent PTY** (e.g., `docker exec -it`, `tmux` inside container, or a PTY proxy) so the process can be paused and resumed.
4. Stream stdout/stderr to the orchestrator for logs + trace correlation.
5. When CC requests input (clarification/permission), the orchestrator triggers a **breakpoint** and keeps the container+PTY alive; after a human response, it feeds the response back to stdin and resumes.

### Safety baseline (host protection) in Docker
- Run as non-root user
- Drop Linux capabilities; use seccomp/AppArmor
- Read-only base filesystem; writable workspace volume only
- Resource limits (CPU/mem/pids); optional network isolation
- No sensitive host mounts; explicit env var allowlist

### Required progress reporting
Structured progress checkpoints are required (not optional).

**Baseline capture (also required):** streamed stdout/stderr logs, git history, and test command output.

**Structured checkpoints (machine-readable):** CC emits progress events at commit/PR boundaries, either:
- as tagged JSON blocks in stdout, or
- written to a `progress.jsonl` file in the workspace (recommended).

**Suggested event schema**
- `type`: `commit_started | commit_green | pr_completed | blocked`
- `pr_id`, `commit_id`
- `files_changed`
- `tests_added`
- `tests_run` (commands + result)
- `status` and `notes`

**Why require checkpoints even with a live session**
- Reliable “where am I?” without reading logs (current PR/commit)
- Better recovery if the live session dies unexpectedly
- Enables evals/metrics later (cycle time per commit, flake rates, etc.)

### Handling CC “needs input” in live session mode
Use an interrupt protocol that the wrapper can detect and convert into orchestrator breakpoints:
- `ARCHIPELAGO_NEED_CLARIFICATION { question, options, default, blocking }`
- `ARCHIPELAGO_NEED_PERMISSION { action, risk_level, why_needed, alternatives }`

The orchestrator pauses the DAG at the breakpoint, surfaces the request to a human, then resumes by sending the response back into the live session.

---

## Optional reliability add-on: recovery/resume fallback
This is not an alternative to live session execution; it is a fallback used when the live container/session is lost (crash, eviction, timeout, orchestrator restart), or when policy requires terminating long-lived sessions.

### What must be persisted
- Workspace state: commit SHA + working tree diff (or a snapshot/volume)
- CC transcript (or a compact “run summary”)
- Latest structured checkpoint indicating current PR/commit and remaining work

### How recovery/resume works
1. Restore workspace snapshot into a fresh container.
2. Restart CC/Codex with: feature spec + last checkpoint + relevant logs/failures.
3. Continue from the last known PR/commit boundary.

### Why implement after live session mode
- Live session execution delivers immediate value (manual-flow replacement) with minimal complexity.
- Recovery/resume hardens reliability and reduces “start over” costs, but requires additional persistence plumbing and disciplined checkpointing.
- The structured checkpoints required in live session mode make recovery/resume straightforward and reliable; without them, resume quality degrades.

DSPy is relevant to Archipelago primarily as an **inner-loop optimization layer** for agent components, not as a replacement for your **workflow orchestrator**.

## What DSPy is (in the terms that matter for Archipelago)

- DSPy is a Python framework for building **modular LM programs** and “compiling” them into effective prompts/parameters via **optimizers** driven by a metric. ([DSPy](https://dspy.ai/?utm_source=chatgpt.com "DSPy"))
    
- It formalizes modules with **Signatures**: declarative input/output specs for an LM call. ([DSPy](https://dspy.ai/learn/programming/signatures/?utm_source=chatgpt.com "Signatures"))
    

This maps cleanly onto your “typed capability” approach: signatures resemble capability I/O schemas, and optimizers resemble your “auto-tune” idea.

## Some Thoughts about DSPy
### How DSPy fits into the Archipelago workflow

#### 1) Use DSPy to improve _specific_ Archipelago agents/components with measurable metrics

Best targets are components where you can define a stable metric and have lots of examples:

- **Spec Linter / Consistency Checker**: classify issues, propose fixes; metric from labeled spec defects or human accept/reject. (DSPy signatures + optimizers fit well.) ([DSPy](https://dspy.ai/learn/programming/signatures/?utm_source=chatgpt.com "Signatures"))
    
- **PR Reviewer Agent**: detect missing tests/edge cases/security items; metric from downstream bug rate, review acceptance, or a rubric. ([DSPy](https://dspy.ai/?utm_source=chatgpt.com "DSPy"))
    
- **Planner sub-tasks** (not the whole orchestrator): e.g., “convert FeatureSpec → PR/commit plan quality score” with a rubric. ([DSPy](https://dspy.ai/learn/optimization/optimizers/?utm_source=chatgpt.com "Optimizers"))
    
- **Retrieval/RAG submodules** (if you do retrieval over artifacts): DSPy has explicit patterns and tutorials for RAG-style pipelines. ([DSPy](https://dspy.ai/tutorials/rag/?utm_source=chatgpt.com "Tutorial: Retrieval-Augmented Generation (RAG) - DSPy"))
    

#### 2) DSPy + your eval harness = “Auto-tune Archipelago” implemented for real

Your earlier plan included a prompt/workflow optimizer. DSPy provides the mechanism: given (program, metric, examples), an optimizer tunes prompts/parameters to maximize the metric. ([DSPy](https://dspy.ai/learn/optimization/optimizers/?utm_source=chatgpt.com "Optimizers"))  
So: **Archipelago Evals** produces scored tasks → DSPy optimizers tune a module → you gate rollout based on eval regression.

#### 3) DSPy is not your orchestrator

DSPy doesn’t give you the control-plane features you need:

- DAG execution across heterogeneous agents/tools
    
- Docker session lifecycle + breakpoints + live pause/resume for Claude Code
    
- artifact store, checkpoint/resume, permissions gating
    

So the right integration is: **Orchestrator owns workflow + state; DSPy owns optimization inside individual LM modules.** ([DSPy](https://dspy.ai/?utm_source=chatgpt.com "DSPy"))

### How to integrate DSPy into “Control Plane Lite”

Treat a DSPy program as just another **capability**:

- `capability_id: spec.lint_dspy` or `review.pr_review_dspy`
    
- Inputs/outputs defined by your canonical schemas; inside the capability you map them to DSPy Signatures. ([DSPy](https://dspy.ai/learn/programming/signatures/?utm_source=chatgpt.com "Signatures"))
    
- Run an offline “compile/optimize” job (DSPy optimizer) as a separate orchestration workflow step, producing a versioned artifact (prompt/weights) that your runtime capability loads. ([DSPy](https://dspy.ai/learn/optimization/optimizers/?utm_source=chatgpt.com "Optimizers"))
    

### Where DSPy is _not_ a good fit (initially)

- Your **Claude Code “implement this feature spec” worker**: CC already has a strong closed-loop with real tests (the best metric). DSPy adds little unless you’re trying to optimize CC’s instruction protocol or checkpoint emission format.
    
- Full end-to-end agentic workflow optimization: DSPy can optimize modules, but end-to-end orchestration changes are better handled by your eval harness + orchestrator-level A/B.
    

### Recommended first DSPy use inside Archipelago

Start with one narrow, high-signal module:

- **Spec Linter** (signature = FeatureSpec → Issues+Fixes; metric = human label/rubric + downstream defect rate proxy), then use a DSPy optimizer to tune it. ([DSPy](https://dspy.ai/learn/programming/signatures/?utm_source=chatgpt.com "Signatures"))
    

If you share which Archipelago component currently has the most variance (spec quality, review quality, planning quality, retrieval quality), I can map it to a DSPy Signature + metric + dataset plan that matches your orchestrator artifacts.