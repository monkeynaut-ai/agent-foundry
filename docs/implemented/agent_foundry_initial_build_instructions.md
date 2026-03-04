# Agent Foundry — Build Instructions

## Post-Build Decisions

The following architectural decisions were made after the initial build and diverge from the original spec:

1. **Step 4 (Wiring Planner) — Removed.** Products own their wiring plans as JSON files. The framework provides schema validation and compilation, but no LLM-driven plan generation. Slices S4.1–S4.7 are no longer applicable.

2. **`structured_output_pydantic` — Removed as a built-in capability.** It is an implementation pattern (using Pydantic for structured LLM output), not a discrete graph node. The capability *name* is still used in demo plans and templates, but no built-in spec ships for it.

3. **DS8 (Planner generates Decision Support plan) — Deferred.** The demo uses a static JSON plan. Dynamic plan generation depends on the removed WiringPlanner.

4. **Separation boundary established.** Agent Foundry (`agent_foundry.*`) must never import from product code (`archipelago.*`). Enforced via `import-linter`. See `docs/agent-foundry-separation-spec.md`.

---

## Objective
Build a **reusable agentic workflow platform** on **LangGraph** (orchestration) using **LangChain** as a component library (models, tools, retrieval, structured outputs, integrations), and use that platform to deliver **one runnable reference demo**: **Decision Support (multi-domain)**.

What this document guarantees:
- A reusable **Capability Registry** + **Retriever** + **Wiring Planner** + **Plan Compiler** + **Eval/Observability** framework.
- A **machine-compilable `GraphWiringPlan`** and a **runnable end-to-end Decision Support demo workflow** that exercises core capabilities and gates.

What this document does not claim by itself:
- Full production-grade domain tooling, complete integrations, or exhaustive feature coverage beyond the Decision Support demo without additional system-specific slices.

---

## High-Level Architecture

### Core shared layers (build once)
1) **Capability Registry**: a catalog of atomic capabilities with metadata, schemas, and implementation factories.
2) **Docs/Registry Retriever**: RAG index over registry + curated LangChain/LangGraph docs snippets.
3) **Wiring Planner**: agent that outputs a **Graph Wiring Plan** as structured JSON/Pydantic.
4) **Plan Compiler**: converts a Wiring Plan into an executable LangGraph by composing reusable node/subgraph templates.
5) **Observability + Evaluation Gates**: tracing + automated checks; optional human-in-the-loop breakpoints.

### Reference demo graph (build one)
- Decision Support demo uses the shared layers to generate/modify a LangGraph wiring plan and compile it.

---

## Build Order (mandatory; follow exactly)

Agents must implement slices in **this exact sequence**, where **each slice is a single PR**. Do not reorder, skip, or parallelize slices.

### Mandatory slice sequence
1) Step 1: S1.1 → S1.8
2) Step 2: S2.1 → S2.7
3) Step 3: S3.1 → S3.6
4) Step 4 (partial): S4.1 → S4.4 → S4.6 → S4.7
5) Step 5: S5.1 → S5.8
6) Step 6: S6.1 → S6.7
7) Step 4 (deferred gate inclusion): S4.5
8) Decision Support demo: DS1 → DS9

### Agent execution rules (to ensure compliance)
- **One PR per slice.** A PR may contain multiple commits, but must only implement the stated slice.
- **TDD required.** Within each PR, commits must follow: tests (red) → implementation (green) → optional refactor.
- **Dependency check before coding.** Before starting a slice, confirm all its listed dependencies are already merged. If any dependency is missing, stop and produce a single error report titled `BUILD_ORDER_BLOCKED` with:
  - the blocked slice id,
  - the missing dependency,
  - the exact document lines that state the dependency.
- **Feature flags.** If a slice is behind a feature flag, implement both:
  - flag OFF behavior (no-op or safe fallback), and
  - flag ON behavior (the feature),
  each covered by independent tests.
- **No human-in-the-loop required to build.** Any HITL/breakpoint features are implemented and tested via simulated approvals/interrupt payloads; do not require interactive input.



---

## Component Map


## Deliverable Slices for Test-Driven Development
Design slices so each PR is a vertical slice delivering deployable value. Each slice includes: description, acceptance criteria coverage, dependencies, and suggested commit breakdown.

---

### Step 1 — Create a Capability Registry
**Goal:** Ensure “how to use LangChain” lives in code + metadata, not in prompts.

#### Deliverable Slices (Step 1)

**S1.1 — Load and validate a single capability spec (happy path)**
- Includes: `CapabilitySpec` schema (Pydantic), loader for one YAML/JSON file, strict required-field validation, round-trip field equality.
- Addresses AC: Step 1 #1, #5.
- Dependencies: none.
- Feature flags: none.
- Suggested commits:
  1) Tests (red): parse + validate valid spec; assert field equality.
  2) Impl (green): `CapabilitySpec`, file loader, schema compile.
  3) Refactor: shared test fixtures.

**S1.2 — Deterministic errors for invalid specs (missing fields + parse errors)**
- Includes: typed exceptions `CapabilitySpecValidationError`, parse error handling with file path and line/column (if available).
- Addresses AC: Step 1 #2, #4.
- Dependencies: S1.1.
- Feature flags: none.
- Suggested commits:
  1) Tests (red): missing `name` yields typed error; invalid YAML/JSON yields parse error with metadata; process does not crash.
  2) Impl (green): exception types, error wrapping, metadata extraction.

**S1.3 — Multi-file registry initialization + duplicate detection**
- Includes: load `capabilities/*.(yaml|json)`, build `CapabilityRegistry`, deterministic duplicate-name detection.
- Addresses AC: Step 1 #3.
- Dependencies: S1.2.
- Feature flags: none.
- Suggested commits:
  1) Tests (red): two specs same `name` -> `DuplicateCapabilityError` with both paths.
  2) Impl (green): directory scanning, registry map, duplicate check.

**S1.4 — Importable implementation pointers + instantiation failure reporting**
- Includes: import resolution for `implementation` pointers; errors become `CapabilityImportError`.
- Addresses AC: Step 1 #6.
- Dependencies: S1.3.
- Feature flags: `FF_CAPABILITY_IMPORTS` (default on).
- Suggested commits:
  1) Tests (red): bad module path -> typed error includes pointer + underlying exception.
  2) Impl (green): import utility, safe import wrapper.

**S1.5 — Execute a capability node with input/output schema enforcement**
- Includes: standard node wrapper enforcing `inputs_schema` and `outputs_schema`, raising `CapabilityExecutionError`, blocking on output mismatch.
- Addresses AC: Step 1 #8, #9.
- Dependencies: S1.4.
- Feature flags: `FF_SCHEMA_ENFORCEMENT` (default on).
- Suggested commits:
  1) Tests (red): valid input returns output; invalid input -> typed error; invalid output -> validation report with field path.
  2) Impl (green): wrapper, validation utilities, error mapping.

**S1.6 — Quality controls: timeouts + retries**
- Includes: enforce per-capability timeout and max retries from `quality_controls`.
- Addresses AC: Step 1 #10.
- Dependencies: S1.5.
- Feature flags: `FF_RETRY_TIMEOUTS` (default off until stabilized).
- Suggested commits:
  1) Tests (red): slow node times out; flaky node retries up to max then errors.
  2) Impl (green): timeout mechanism, retry loop, metrics hooks.

**S1.7 — Minimum capability set present + searchable by tags**
- Includes: ship stub capability specs for required minimum list; `search(tags=...)` deterministic sorting.
- Addresses AC: Step 1 #7, #12.
- Dependencies: S1.3.
- Feature flags: `FF_MIN_CAP_SET` (default on).
- Suggested commits:
  1) Tests (red): registry contains all minimum capability names; tag search returns correct set sorted.
  2) Impl (green): add spec fixtures + search API.

**S1.8 — Non-functional: startup performance budget**
- Includes: benchmark test harness for registry startup under N=100.
- Addresses AC: Step 1 #11.
- Dependencies: S1.7.
- Feature flags: `FF_BENCHMARKS` (CI nightly).
- Suggested commits:
  1) Tests (red): benchmark asserts p95 ≤ 500ms (marked performance).
  2) Impl (green): optimize scanning/parsing, add caching if needed.

---

### Step 2 — Build a Retriever over Registry + Docs
**Goal:** Give planners reliable, current guidance and reduce hallucinated API usage.

#### Deliverable Slices (Step 2)

**S2.1 — Corpus ingestion + persisted index (happy path)**
- Includes: ingest registry specs + curated docs into a corpus, build and persist an index, reload without rebuild.
- Addresses AC: Step 2 #1.
- Dependencies: S1.7 (registry provides specs).
- Feature flags: `FF_RETRIEVER` (default off until S2.3).
- Suggested commits:
  1) Tests (red): build index creates files; reload works; rebuild not required.
  2) Impl (green): indexer, persistence layer, config.

**S2.2 — Deterministic retrieval ordering + stable ids**
- Includes: stable chunk ids/hashes; deterministic retrieval config.
- Addresses AC: Step 2 #5, #6.
- Dependencies: S2.1.
- Feature flags: `FF_DETERMINISTIC_RETRIEVAL` (default on).
- Suggested commits:
  1) Tests (red): same query twice returns identical ids + ordering; rerun indexing yields identical doc ids.
  2) Impl (green): chunking/id scheme, retrieval settings.

**S2.3 — Retrieval API returns capability snippets for exact name queries**
- Includes: `retrieve(query)->[snippets]`, top-3 includes exact capability spec snippet.
- Addresses AC: Step 2 #2.
- Dependencies: S2.2.
- Feature flags: `FF_RETRIEVER` (default on).
- Suggested commits:
  1) Tests (red): query="rag_retriever" returns snippet referencing that spec in top-3.
  2) Impl (green): query router, ranking, snippet formatting.

**S2.4 — No-hit behavior + explicit logging**
- Includes: empty list return and `no_hits` log event.
- Addresses AC: Step 2 #3.
- Dependencies: S2.3.
- Feature flags: none.
- Suggested commits:
  1) Tests (red): nonsense query returns []; log captured contains “no_hits”.
  2) Impl (green): logging hook.

**S2.5 — Robust failures: corrupted index + vector store outage**
- Includes: `IndexLoadError` on corrupted/missing index; `RetrieverUnavailableError` on backend outage.
- Addresses AC: Step 2 #4, #9.
- Dependencies: S2.1.
- Feature flags: none.
- Suggested commits:
  1) Tests (red): missing/corrupt index raises `IndexLoadError`; backend down raises `RetrieverUnavailableError`.
  2) Impl (green): error mapping and detection.

**S2.6 — Snippet limits + source metadata**
- Includes: max snippet length truncation; include doc id + offsets.
- Addresses AC: Step 2 #7.
- Dependencies: S2.3.
- Feature flags: none.
- Suggested commits:
  1) Tests (red): snippet length ≤ configured max; metadata present.
  2) Impl (green): truncation + metadata.

**S2.7 — Non-functional: retrieval latency budgets**
- Includes: benchmark harness for 100 queries; enforce median/p95 budgets.
- Addresses AC: Step 2 #8.
- Dependencies: S2.3.
- Feature flags: `FF_BENCHMARKS` (CI nightly).
- Suggested commits:
  1) Tests (red): perf test asserts median ≤ 50ms and p95 ≤ 200ms.
  2) Impl (green): optimize store/query, caching.

---

### Step 3 — Define the Graph Wiring Plan (Structured Output)
**Goal:** Planning outputs must be machine-compilable.

#### Deliverable Slices (Step 3)

**S3.1 — Pydantic model + JSON round-trip (happy path)**
- Includes: `GraphWiringPlan` model with core fields; parse + serialize round-trip.
- Addresses AC: Step 3 #1.
- Dependencies: S1.7 (capability names exist).
- Feature flags: none.
- Suggested commits:
  1) Tests (red): valid JSON parses; `.model_dump_json()` round-trips with no field loss.
  2) Impl (green): Pydantic models.

**S3.2 — Structural validation errors (missing required fields)**
- Includes: clear error messages with JSON paths.
- Addresses AC: Step 3 #2.
- Dependencies: S3.1.
- Feature flags: none.
- Suggested commits:
  1) Tests (red): missing `nodes` yields message including path.
  2) Impl (green): model config + custom error formatter.

**S3.3 — Referential integrity: unknown capabilities, dangling edges, duplicate node ids**
- Includes: plan validator that checks registry membership, node id uniqueness, edge endpoints.
- Addresses AC: Step 3 #3, #4, #5.
- Dependencies: S3.1 + S1.7.
- Feature flags: `FF_PLAN_VALIDATION` (default on).
- Suggested commits:
  1) Tests (red): unknown capability -> `UnknownCapabilityError`; duplicate ids -> `DuplicateNodeIdError`; dangling edge -> `DanglingEdgeError`.
  2) Impl (green): validator functions.

**S3.4 — Tool calling contract in plans**
- Includes: if any node uses `tool_calling`, require `tools` list with unique names + arg schemas.
- Addresses AC: Step 3 #6.
- Dependencies: S3.3.
- Feature flags: none.
- Suggested commits:
  1) Tests (red): plan with tool_calling but no tools fails; duplicate tool names fails.
  2) Impl (green): validation rule.

**S3.5 — Breakpoints and persistence validation**
- Includes: breakpoints reference existing nodes; persistence has required non-empty fields.
- Addresses AC: Step 3 #7, #8.
- Dependencies: S3.3.
- Feature flags: `FF_PERSISTENCE` (default off until Step 5 S5.4).
- Suggested commits:
  1) Tests (red): breakpoint to missing node fails; persistence missing backend fails.
  2) Impl (green): validation rules.

**S3.6 — Versioning coverage + loop termination enforcement**
- Includes: capability_versions must cover all node types; loops require termination condition or max iterations.
- Addresses AC: Step 3 #9, #10.
- Dependencies: S3.3.
- Feature flags: none.
- Suggested commits:
  1) Tests (red): missing capability_versions entry fails; loop without termination fails.
  2) Impl (green): validator rules.

---

### Step 4 — Build the Wiring Planner Agent
**Goal:** Agents “figure out” LangChain usage by selecting capabilities from the registry.

#### Deliverable Slices (Step 4)

**S4.1 — Minimal planner that emits a valid plan without retrieval**
- Includes: deterministic planner that selects a minimal set of nodes based on goal; produces valid `GraphWiringPlan` JSON.
- Addresses AC: Step 4 #1, #2.
- Dependencies: Step 3 (S3.6) + Step 1 (S1.7).
- Feature flags: `FF_PLANNER` (default off until S4.3).
- Suggested commits:
  1) Tests (red): planner output validates against model; all node types in registry.
  2) Impl (green): planner scaffolding, deterministic settings.

**S4.2 — Retrieval integration: planner consumes snippets**
- Includes: feed retrieved snippets into planner input; planner still emits valid plan.
- Addresses AC: Step 4 #1.
- Dependencies: Step 2 (S2.4) + S4.1.
- Feature flags: `FF_PLANNER_RETRIEVAL` (default off).
- Suggested commits:
  1) Tests (red): with snippets present, planner includes referenced capabilities; still valid.
  2) Impl (green): retriever adapter, prompt/context composer.

**S4.3 — Tool selection and tool schema emission**
- Includes: if goal requires tools, planner selects `tool_calling` and emits non-empty `tools` list with unique names.
- Addresses AC: Step 4 #3.
- Dependencies: Step 3 (S3.4) + S4.2.
- Feature flags: `FF_PLANNER` (default on after this slice).
- Suggested commits:
  1) Tests (red): tool-required goal leads to tool_calling node + tools list; duplicate prevented.
  2) Impl (green): tool requirement detection, tool schema generator.

**S4.4 — Risk-aware HITL placement**
- Includes: if risk=high and irreversible tool present, include `human_approval_gate` breakpoint before execution.
- Addresses AC: Step 4 #4.
- Dependencies: Step 1 (human_approval_gate spec present) + Step 3 (S3.5) + S4.3.
- Feature flags: `FF_HITL` (default off until Step 5 S5.4).
- Suggested commits:
  1) Tests (red): irreversible tool under high risk inserts breakpoint.
  2) Impl (green): risk rules + breakpoint insertion.

**S4.5 — Eval gate inclusion + reachability**
- Includes: planner always includes ≥1 eval gate and ensures at least one is reachable from start.
- Addresses AC: Step 4 #5.
- Dependencies: Step 6 capability specs exist (can be stubbed) + S4.1.
- Feature flags: `FF_EVAL_GATES` (default on).
- Suggested commits:
  1) Tests (red): plan contains eval_gates; graph reachability analysis says reachable.
  2) Impl (green): gate selection + reachability check.

**S4.6 — No-snippet behavior: minimal plan or typed failure**
- Includes: if retrieval empty, planner either emits minimal plan or raises `PlanningInsufficientContextError`.
- Addresses AC: Step 4 #6.
- Dependencies: S4.2.
- Feature flags: none.
- Suggested commits:
  1) Tests (red): retrieval empty triggers minimal plan OR typed error (configurable).
  2) Impl (green): fallback strategy + error.

**S4.7 — Determinism + budget enforcement + concurrency**
- Includes: deterministic config yields byte-identical JSON; planning timeout; concurrency safety.
- Addresses AC: Step 4 #7, #8, #9.
- Dependencies: S4.3.
- Feature flags: `FF_PLANNER_BUDGETS` (default on).
- Suggested commits:
  1) Tests (red): run planner twice yields identical bytes; forced timeout yields `PlanningTimeoutError`.
  2) Impl (green): deterministic seeds, timeout wrapper.
  3) Tests (red): 50 concurrent calls don’t crash; p95 ≤ 2s (perf test).
  4) Impl (green): thread-safe components, pooling.

---

### Step 5 — Build the Plan Compiler (LangGraph Builder)
**Goal:** Convert plans into executable LangGraph graphs.

#### Deliverable Slices (Step 5)

**S5.1 — Compile + run a trivial graph with one node**
- Includes: `compile_plan` that validates plan, instantiates one node from registry, runs with initial state.
- Addresses AC: Step 5 #1.
- Dependencies: Step 1 (S1.5) + Step 3 (S3.3).
- Feature flags: `FF_COMPILER` (default off until S5.2).
- Suggested commits:
  1) Tests (red): compile returns runnable; invocation produces expected state mutation.
  2) Impl (green): compiler skeleton, node instantiation.

**S5.2 — Fail-fast compile errors (invalid plan, instantiation errors)**
- Includes: `PlanValidationError` and `CapabilityInstantiationError` with node id + capability.
- Addresses AC: Step 5 #2, #3.
- Dependencies: S5.1.
- Feature flags: none.
- Suggested commits:
  1) Tests (red): invalid plan fails fast; factory raises -> typed error includes node id.
  2) Impl (green): error handling.

**S5.3 — Conditional edges + branch logging**
- Includes: support condition evaluation and branch decision logs.
- Addresses AC: Step 5 #4.
- Dependencies: S5.1.
- Feature flags: `FF_CONDITIONAL_EDGES` (default on).
- Suggested commits:
  1) Tests (red): state triggers correct branch; log event captured.
  2) Impl (green): condition evaluator + logging.

**S5.4 — Loop safety: max-iterations enforcement**
- Includes: loop construct support (or conditional edge loop) with `MaxIterationsExceededError`.
- Addresses AC: Step 5 #5.
- Dependencies: S5.3.
- Feature flags: `FF_LOOPS` (default on).
- Suggested commits:
  1) Tests (red): non-terminating loop halts at N with typed error.
  2) Impl (green): iteration counter + stop.

**S5.5 — Breakpoints (interrupt payload) + HITL plumbing**
- Includes: execution pauses at breakpoint node; returns interrupt payload with pending action summary.
- Addresses AC: Step 5 #7.
- Dependencies: Step 3 (S3.5) + S5.3.
- Feature flags: `FF_HITL` (default off until S5.6).
- Suggested commits:
  1) Tests (red): reaching breakpoint returns interrupt payload; downstream irreversible node not executed.
  2) Impl (green): breakpoint mechanism.

**S5.6 — Persistence: checkpoint, interrupt, resume deterministically**
- Includes: checkpoint backend + thread id; resume restores state and continues.
- Addresses AC: Step 5 #6.
- Dependencies: S5.5.
- Feature flags: `FF_PERSISTENCE` (default on after this slice).
- Suggested commits:
  1) Tests (red): interrupt + resume yields identical outputs after resume (deterministic).
  2) Impl (green): checkpointing integration.

**S5.7 — Template expansion into subgraphs**
- Includes: handle requests for `draft_review_revise_loop`, `gather_verify_analyze_recommend`, `plan_execute_test_fix_retest` by expanding to valid registry nodes.
- Addresses AC: Step 5 #8.
- Dependencies: S5.3.
- Feature flags: `FF_TEMPLATES` (default off until templates validated).
- Suggested commits:
  1) Tests (red): template reference expands to subgraph; all node types exist in registry.
  2) Impl (green): template library + expander.

**S5.8 — Runtime schema failures block downstream + compile-time performance budget**
- Includes: schema enforcement hook at runtime; compiler perf test harness.
- Addresses AC: Step 5 #9, #10.
- Dependencies: S5.1 + Step 1 (S1.5).
- Feature flags: `FF_BENCHMARKS` (CI nightly).
- Suggested commits:
  1) Tests (red): invalid node output blocks downstream and reports schema path.
  2) Impl (green): runtime guard.
  3) Tests (red): compile p95 ≤ 300ms for ≤50 nodes.
  4) Impl (green): optimize compile.

---

### Step 6 — Add Observability + Evaluation Gates
**Goal:** Measure what works and prevent low-quality outputs.

#### Deliverable Slices (Step 6)

**S6.1 — Tracing spans for node execution**
- Includes: trace span per node with timestamps, node id, capability, status; export interface.
- Addresses AC: Step 6 #1.
- Dependencies: Step 5 (S5.1).
- Feature flags: `FF_TRACING` (default on).
- Suggested commits:
  1) Tests (red): executing graph emits spans with required fields.
  2) Impl (green): tracer + span model.

**S6.2 — Tool and retrieval trace enrichment**
- Includes: capture tool call args/results with redaction; record retrieval snippet ids/ranks.
- Addresses AC: Step 6 #2, #3.
- Dependencies: S6.1 + Step 2 (S2.3).
- Feature flags: `FF_TRACE_TOOL_IO` (default on), `FF_TRACE_RETRIEVAL` (default on).
- Suggested commits:
  1) Tests (red): tool traces redact secrets; retrieval traces include snippet metadata.
  2) Impl (green): redaction + enrichers.

**S6.3 — Schema validator gate (generic)**
- Includes: `schema_validator` capability; failure blocks final.
- Addresses AC: Step 6 #4.
- Dependencies: Step 1 (S1.5) + Step 5 (S5.1).
- Feature flags: `FF_EVAL_GATES` (already on).
- Suggested commits:
  1) Tests (red): invalid output triggers schema gate failure and blocks final response.
  2) Impl (green): validator node.

**S6.4 — Decision eval gates: citation, uncertainty, evidence-first**
- Includes: `citation_validator`, `uncertainty_completeness_validator`, `evidence_first_contract` with structured failure reports.
- Addresses AC coverage: Decision Support demo gates; Step 6 gating patterns.
- Dependencies: S6.3.
- Feature flags: `FF_DOMAIN_GATES` (default off until tuned).
- Suggested commits:
  1) Tests (red): missing evidence ids fails citation gate; missing uncertainty fields fails uncertainty gate; empty evidence triggers evidence-first failure with typed outcome.
  2) Impl (green): each validator + report format.

**S6.6 — Compiler enforces gate execution on all paths to final**
- Includes: static analysis during compile ensuring at least one eval gate on every path to final node.
- Addresses AC: Step 6 #10.
- Dependencies: Step 5 (S5.3).
- Feature flags: none.
- Suggested commits:
  1) Tests (red): plan missing gate on one path fails compilation.
  2) Impl (green): path analysis + enforcement.

**S6.7 — Non-functional: trace payload size + export latency budgets**
- Includes: enforce 256KB max span payload; export p95 ≤ 500ms for 1,000 spans.
- Addresses AC: Step 6 #11.
- Dependencies: S6.1.
- Feature flags: `FF_BENCHMARKS` (CI nightly).
- Suggested commits:
  1) Tests (red): oversize payload is truncated/rejected deterministically; perf test meets budget.
  2) Impl (green): payload limiter + export optimization.

---

## Decision Support Demo (Reference Implementation)
**Pattern:** evidence-first recommendation contract.

### Demo scope
A single runnable workflow that:
1) takes a user question + optional constraints,
2) retrieves evidence,
3) optionally calls tools,
4) produces a structured recommendation with evidence ids, assumptions, and uncertainty,
5) enforces eval gates that block final output on missing evidence/uncertainty.

### Required state fields (demo)
- `question`
- `domain`
- `constraints`
- `retrieved_evidence` (snippets + ids)
- `analysis`
- `recommendation` (structured)
- `assumptions`
- `uncertainty`

### Required capabilities (demo)
- `rag_retriever`
- `structured_output_pydantic`
- `tool_calling` (demo uses a stub calculator tool)
- `schema_validator`
- `citation_validator`
- `uncertainty_completeness_validator`
- `evidence_first_contract`

### Deliverable Slices (Decision Support Demo)

**DS1 — Runnable demo entrypoint with a static plan (no LLM/tools yet)**
- Includes: a CLI/API runner that loads a checked-in Decision Support `GraphWiringPlan` JSON and executes a trivial graph that returns a canned structured recommendation.
- Addresses AC: Build acceptance #3–#4.
- Dependencies: Step 3 (S3.6), Step 5 (S5.1).
- Feature flags: `FF_DECISION_DEMO` (default on).
- Suggested commits:
  1) Tests (red): runner loads plan JSON and executes graph producing expected output object.
  2) Impl (green): runner + static plan fixture + minimal graph wiring.

**DS2 — Evidence retrieval node + evidence written to state**
- Includes: `rag_retriever` node in the demo plan; evidence stored as `{id, text, source}` list; determinism for id assignment.
- Addresses AC: Step 2 (retrieval behavior), Step 6 (retrieval tracing).
- Dependencies: Step 2 (S2.3–S2.6), Step 5 (S5.3), Step 6 (S6.2).
- Feature flags: `FF_DECISION_RETRIEVAL` (default on).
- Suggested commits:
  1) Tests (red): given a query, when demo runs, then `retrieved_evidence` contains ≥1 item with non-empty `id` and `text`.
  2) Impl (green): add retrieval node + state mapping + evidence id strategy.

**DS3 — Structured recommendation schema enforced (no tools)**
- Includes: `structured_output_pydantic` node producing a `Recommendation` model with fields: `recommendation`, `evidence_ids`, `assumptions[]`, `uncertainty`.
- Addresses AC: Step 1 schema enforcement, Step 6 `schema_validator`.
- Dependencies: Step 1 (S1.5), Step 6 (S6.3).
- Feature flags: `FF_DECISION_STRUCTURED_OUTPUT` (default on).
- Suggested commits:
  1) Tests (red): malformed recommendation output fails schema and blocks final.
  2) Impl (green): Pydantic models + node wrapper + plan update.

**DS4 — Citation validator gate: claims must reference evidence ids**
- Includes: `citation_validator` gate that checks `recommendation.evidence_ids` are all present in `retrieved_evidence.id` and fails with missing refs list.
- Addresses AC: build acceptance #5 (citations).
- Dependencies: Step 6 (S6.4) and Step 5 (S5.3).
- Feature flags: `FF_DECISION_CITATIONS` (default on).
- Suggested commits:
  1) Tests (red): given recommendation with an evidence id not in retrieved set, when gate runs, then it fails and final output is not produced.
  2) Impl (green): citation validator capability + wire into plan.

**DS5 — Uncertainty completeness validator gate**
- Includes: `uncertainty_completeness_validator` gate requiring: numeric confidence in [0,1] AND a natural-language uncertainty rationale.
- Addresses AC: build acceptance #5 (uncertainty).
- Dependencies: Step 6 (S6.4) + DS3.
- Feature flags: `FF_DECISION_UNCERTAINTY` (default on).
- Suggested commits:
  1) Tests (red): missing confidence or rationale fails gate with field-specific errors.
  2) Impl (green): validator capability + plan wiring.

**DS6 — Evidence-first contract validator (end-to-end policy)**
- Includes: `evidence_first_contract` validator enforcing:
  - if `retrieved_evidence` is empty, return a typed “insufficient evidence” outcome (no recommendation),
  - recommendation must list assumptions explicitly.
- Addresses AC: build acceptance #5 (evidence contract).
- Dependencies: DS2, DS4, DS5.
- Feature flags: `FF_DECISION_EVIDENCE_CONTRACT` (default on).
- Suggested commits:
  1) Tests (red): no evidence → returns typed insufficient-evidence output and does not emit recommendation; missing assumptions fails.
  2) Impl (green): validator + alternative output path.

**DS7 — Tool-calling node with a stub calculator tool + tracing**
- Includes: `tool_calling` node that can call a deterministic calculator tool; trace includes tool name + args + output with redaction.
- Addresses AC: Step 6 tool tracing.
- Dependencies: Step 6 (S6.2), Step 3 (S3.4), Step 1 (S1.5).
- Feature flags: `FF_DECISION_TOOLS` (default off until stable).
- Suggested commits:
  1) Tests (red): question requiring arithmetic triggers tool call and returns correct computed value; trace contains tool call record.
  2) Impl (green): calculator tool + tool_calling capability wiring.

**DS8 — Planner produces the Decision Support demo plan (replacing static plan)**
- Includes: planner config to generate the Decision Support plan deterministically from a “decision-support” goal; outputs byte-identical plan.
- Addresses AC: build acceptance #2.
- Dependencies: Step 4 (S4.3, S4.7) + DS1–DS6.
- Feature flags: `FF_DECISION_PLANNER` (default off; keep static plan as fallback).
- Suggested commits:
  1) Tests (red): planner emits valid plan that matches expected node types and required gates.
  2) Impl (green): decision-support planner adapter + deterministic settings.

**DS9 — Non-functional: end-to-end latency and failure-mode budgets**
- Includes: perf tests for demo run; explicit timeout budgets on nodes.
- Targets:
  - Without network tools: end-to-end p95 ≤ 2s (reference machine)
- Dependencies: DS2–DS6.
- Feature flags: `FF_BENCHMARKS` (CI nightly).
- Suggested commits:
  1) Tests (red): perf test asserts p95 ≤ 2s; forced slow node times out and returns typed error.
  2) Impl (green): timeouts + minor optimizations.

---

## Acceptance Criteria
A build is acceptable when:
1) You can load the Capability Registry and retrieve capability specs.
2) A valid Wiring Plan for Decision Support is available as a static JSON file (planner-based generation deferred — see Post-Build Decisions).
3) Compiler can compile the Decision Support plan into a runnable LangGraph.
4) The Decision Support demo runs at least one end-to-end workflow.
5) Eval gates prevent final output when validators fail (schema, citations, uncertainty, evidence contract).

---

## Completion Checklist
- All slices S1.1–S6.7 and DS1–DS9 are implemented and passing tests.
- Feature-flagged slices are enabled/disabled according to their defaults and have explicit tests for both states where applicable.

