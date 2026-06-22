# Analyze MLflow for Uses in Agent Foundry

This document analyzes MLflow (https://mlflow.org/) capabilities in the context of agent-foundry and then suggest possible uses. Higher weight is given to capabilities that benefit users of agent foundry and applications built on agent foundry with particular focus on the three pillars of agent foundry:
(1) knowledge is a strategic asset
(2) reducing the time needed to build high-quality agentic systems is a strategic advantage
(3) the cost of AI (API requests, subscriptions, AI tools) will increase dramatically and agent-foundry will help mitigate this risk

## Implementation Status (as of 2026-04-30)

### Implemented

**Use case 1 — MLflow Tracing as AF's telemetry substrate** is the only use case that has been implemented. Design doc: `docs/design/mlflow-tracing-integration-design.md`. Implementation plan: `docs/internal/history/2026-04-27-mlflow-tracing-integration-plan.md`.

What's in place:
- `src/agent_foundry/telemetry/` — OTel-only AF core module: `TelemetryConfig`, `RunDefinition`, `RedactionPolicy`, `RunStats`, `ArtifactSpec`, canonical attribute constants, `emit_span` context manager, `build_tracer_provider`.
- `src/agent_foundry/mlflow_adapter/` — optional `[mlflow]` extra: emit-time attribute translation (`MLFLOW_TRANSLATIONS`), `enable()` entry point, MLflow Run lifecycle hooks (`attach_run_hooks`).
- `AgentRunContext` renamed to `RunContext`; `on_run_starting` / `on_run_ended` typed lifecycle hooks added to `RunContext` with `RunStartingEvent` / `RunEndedEvent` payloads.
- `RUN_FAILED` terminal lifecycle event; `summary.py` updated to render "failed" status.
- Span emission wired into the compiler at `AgentAction` boundaries (both async and sync paths).
- `examples/mlflow_demo/` end-to-end demo with `docker-compose.yaml`.
- Full test coverage in `tests/agent_foundry/telemetry/` and `tests/agent_foundry/mlflow_adapter/`.

What remains within use case 1:
- `src/agent_foundry/observability/` directory not fully removed (Python files deleted; directory shell with `__pycache__` still on disk).
- Span coverage for non-`AgentAction` primitives (`Sequence`, `Loop`, `Retry`, `Conditional`, `FunctionAction`, `GateAction`).
- `RunStats.span_count`, `error_count`, `total_input_tokens`, `total_output_tokens` are hard-coded zeros — per-span accumulation not yet implemented.
- Tail-based sampling.
- Active validation against non-MLflow OTel backends (Langfuse, Jaeger, etc.).

### Not yet started

**Use case 2 — Prompt Registry as backing store for primitive callable fields.** No implementation. Would wire `prompt_builder` / `instructions_provider` fields to MLflow's Prompt Registry by alias (`@production`, `@canary`). Prompt-version linkage on spans.

**Use case 3 — AI Gateway as the routed LLM executor.** No implementation. Would add a Gateway-backed executor option to AF's `executor` field, providing centralized rate limiting, cost caps, and provider failover.

**Use case 4 — Evaluation Datasets + LLM judges for AF regression testing.** No implementation. Depends on use case 1 (tracing) being in place. Would compile any AF primitive into a `predict_fn` for `mlflow.evaluate`, with built-in scorers for schema fidelity, instruction adherence, and latency/cost budgets.

**Use case 5 — Trace → Dataset flywheel.** No implementation. The compounding loop (prod traffic → sampled traces → curated dataset → regression suite → faster confident deploys → more traffic) has no tooling yet. Depends on use cases 1 and 4.

**Use case 6 — Stream-output translator.** No implementation. An adapter family converting per-framework event streams (claude-code JSONL, CrewAI, etc.) to canonical AF spans. Lower priority; only worth building once AF owns a stable span model from use case 1.

## Analysis

MLflow has quietly pivoted into a GenAI platform. Its 2026 surface area sits in two buckets:

- GenAI / Agents: Tracing (OpenTelemetry‑compatible, auto‑instrumented for OpenAI, Anthropic, LangChain, LangGraph, LlamaIndex, DSPy), Evaluation (LLM‑as‑judge + evaluation datasets + human feedback), Prompt Registry (git‑style versioned prompts with aliases + dynamic loading), AI Gateway (unified LLM API with rate limiting and cost control), Agent Server (FastAPI hosting + streaming).
- Classical ML: Experiment Tracking, Model Registry, MLflow Models packaging, Deployment.

Apache‑2.0, self‑hostable. Framework‑agnostic. Same LangChain/LangGraph axis AF already rides.

### Mapping to AF's three pillars

Pillar 1 — Knowledge as strategic asset. MLflow is a learning‑infrastructure product. Traces are the unit of observation; human feedback attaches to traces; evaluation datasets are harvested from production traces; LLM judges scale the grading; prompt versions diff like git. This is exactly the "always be capturing data" and "clever uses of jq" thread in the vision doc, but productized and addressable by downstream tooling rather than ad‑hoc shell.

Pillar 2 — MVP speed & iteration velocity. One‑line auto‑tracing, out‑of‑the‑box LLM scorers, and a prompt registry with aliases materially shrink "change → observe outcome" loops. Builders on AF get observability and eval without writing instrumentation.

Pillar 3 — Cost mitigation. AI Gateway = unified provider shim with rate limits and cost caps. Per‑span token capture = raw data for cost attribution. Sampling ratios = control observability cost itself. All directly on‑target for the future-cost-risk thesis.

## Possible Uses

1. MLflow Tracing as AF's telemetry substrate. The AF compiler wraps each action primitive emission into MLflow spans. Every AF app inherits full trace observability for free — calls, tools, retrievals, tokens, latency, cost, feedback attachment, prod → dataset harvesting. OpenTelemetry compat means products that want their own backend can swap it. Hits pillars 1 + 2 + 3 simultaneously and maps cleanly onto AF's "accumulated state" model (each step's input/output is a natural span boundary).

2. Prompt Registry as backing store for primitive callable fields. AF's callable fields (prompts, instructions) are exactly what the Prompt Registry versions. Register them under an alias scheme (production, canary, experiment-<id>); primitive loads them via load_prompt(...@alias) at compile/run time with TTL cache. This directly delivers the "declaration is the unit being versioned and graded" capability CLAUDE.md already anticipates — without AF building versioning machinery. Covers the "dynamic agent instructions, customize for each job" idea in the vision's Ideas list.

3. AI Gateway as the routed LLM executor. Add a Gateway‑backed executor option to AF's executor field (alongside container/SDK/API). Products that pick it inherit centralized rate limiting, fallback, and cost caps without their own plumbing. Most direct Pillar 3 hit available.

4. Evaluation Datasets + LLM judges for AF regression testing. Compile any AF Sequence/Loop/Gate into a predict_fn for mlflow.evaluate. Ship a first‑party scorer set covering the properties AF cares about (adherence to instructions, tool‑use distribution, schema fidelity, latency/token budget) plus a documented extension point for product‑specific judges. Gives every AF product an evaluation harness out of the box.

5. Trace → Dataset flywheel. MLflow already productizes the "sample prod traces, promote to eval dataset, attach expert annotations, re‑run against new versions" loop. Wire this into AF so the builder journey "First Week → Ongoing" in the vision doc has a concrete shape: your prod traffic becomes your regression suite.

6. Stream‑output translator. The vision doc's jq recipes over claude‑code stream output are a special case of structured tracing. Publish an AF adapter that converts agent stream JSONL into MLflow spans — the UI, diffs, aggregations, and judge pipelines then come for free. Deprecates hand‑rolled jq over time.

### Lower priority / pass

- Prompt Optimization (auto‑mutation). Interesting but crosses into product decisions. If included, expose as an explicit utility a product invokes never as a silent layer.
- Classical experiment tracking for ML. Not the AF job‑to‑be‑done. graded" capability CLAUDE.md already anticipates — without AF building versioning machinery. Covers the  "dynamic agent instructions, customize for each job" idea in the vision's Ideas list.

### Recommendation

Prototype items 1 (Tracing), 2 (Prompt Registry backing), and 3 (AI Gateway executor) first — they are the ones that flow straight through to every product built on AF and they touch all three pillars. Item 4 (evaluation) follows naturally once 1 and 2 are in place.

## Strategic Cautions

- Don't let MLflow opinions leak into AF defaults. AF's "no default for semantic choices, deny‑by‑default for access" principle must hold. MLflow becomes a backing service, not a concept in AF's public surface. Builders read primitive declarations, not MLflow runs.

> **Clarification**
>
> MLflow ships with its own reasonable defaults. If AF adopts them silently, those defaults become AF defaults by accident and break two AF rules from CLAUDE.md:
>
> - "No default for semantic choices" — e.g. MLflow's Prompt Registry resolves @production if no alias is given. If AF's primitive silently loads "latest production" when the product didn't specify a version, AF has quietly made a product decision about which prompt runs.
> - "Deny‑by‑default for access" — e.g. mlflow.openai.autolog() instruments everything and ships spans to a tracing backend. If AF auto‑enables tracing on every primitive, data egress happens without the product opting in — a silent grant of access.
>
> The rule: every MLflow behavior that carries meaning (which prompt version, which model, which provider, where traces go, what gets logged) must be an explicit field on the primitive. MLflow becomes a backing service the product configures, never a source of implicit behavior.

- Abstraction boundary matters. Wrap MLflow in a narrow AF interface (Telemetry, PromptStore, Evaluator, LLMGateway) so MLflow can be swapped if it drifts or if a product needs something else. Matches AF's registry/extension pattern.
- Licensing & deploy model are favorable. Apache‑2.0, self‑hostable — no per‑seat tax on observability, which itself is a Pillar‑3 win versus SaaS competitors (Langfuse, LangSmith, Arize).

## Considerations when Expanding Past LangGraph and LangChain

Most of MLflow's value surface is already framework-agnostic. The shift mostly strengthens the recommendations, with one principle change.

What stays the same or strengthens

- AI Gateway (#3) — strongest fit becomes stronger. It operates at the HTTP/provider layer, below any framework. CrewAI, AutoGen, smolagents, hand‑rolled — they all
still hit api.openai.com. The gateway captures cost/rate control regardless of which orchestration framework is running.
- Prompt Registry (#2) — unaffected. Templates + metadata + aliases are framework-neutral. Any framework that consumes a string can load via load_prompt.
- Evaluation (#4) — unaffected. Just needs predict_fn(inputs) -> outputs. AF can compile any primitive into that signature regardless of the executor underneath.

What needs reshaping

- Tracing (#1) — drop reliance on MLflow's per‑framework autolog() helpers. They're convenient for LangChain/LangGraph but become uneven coverage as the framework
set grows. AF's compiler should emit OpenTelemetry spans at primitive boundaries (Sequence/Loop/Action — these are AF concepts, framework‑agnostic). MLflow becomes
one OTel sink; the spans are well‑defined whether the leaf executor is LangGraph, CrewAI, or a raw API call. This also removes a soft lock‑in to MLflow —
Langfuse/Arize/Jaeger become drop‑in alternatives.
- Stream-output translator (#6) — graduates from "claude code adapter" to a small adapter family: one per framework's event stream → canonical AF span model. Worth
doing only because AF already owns the span model.

New principle to adopt

AF emits OTel; MLflow is a consumer. Don't bind AF's tracing to MLflow's SDK or to any framework's autologger. The Telemetry interface should target OTel primitives
(spans, attributes, links), not MLflow concepts (runs, experiments). MLflow then plugs in as a backend, alongside any other OTel‑compatible store. This protects
pillar 3 (no lock‑in cost) and keeps AF honest about what's its own concept versus what's borrowed.

Net effect on priority ordering

Same top three (Gateway, Prompt Registry, Tracing), but Tracing's implementation is "OTel‑first, MLflow as backend" rather than "MLflow autolog." No recommendation
drops; one ordering nuance — Gateway becomes the most obvious early win because it's the most framework‑indifferent piece of the stack.

### Keep in Mind

- MLFlow currently supports only the OLTP/HTTP endpoint. It does not support the OTLP/gRPC endpoint. This is OK for prototyping. If AF deployments end up needing gRPC, run an OTel Collector as a sidecar to bridge gRPC→HTTP.

## Deeper Dive

### Traces

A flywheel is a loop where each turn produces output that becomes input that accelerates the next turn — the system gathers momentum from its own operation rather
than needing fresh fuel each cycle. (Amazon's selection/price/customer loop is the canonical example.) Calling something a "flywheel" rather than a "pipeline" is a
claim about self-reinforcement.

The specific loop

1. Prod traffic runs through AF primitives → MLflow Tracing captures every span (already free once tracing is on).
2. A sampler promotes interesting traces (errors, low‑judge scores, edge inputs, user-flagged) into candidate evaluation cases.
3. Annotation — human expert or LLM judge — attaches expected output / quality label to each candidate. Now it's a dataset row.
4. The accumulated dataset becomes the regression suite. Every new primitive version (prompt, instructions, model, executor) runs against it.
5. Confident deploys ship faster → more prod traffic → back to step 1.

Why "flywheel" and not "pipeline"

- A pipeline is one‑shot: input → output → done. You'd refill the inputs from somewhere else.
- This loop has no separate fuel source. The exhaust of running the product in prod (traces) is what fuels the next round of evaluation. The dataset grows
monotonically as a byproduct of normal operation. Each turn:
- Dataset is larger and more representative.
- Regression coverage is stronger.
- New version evaluations are more rigorous → safer to ship → more iterations possible.
- More iterations + more traffic → more candidate traces → bigger dataset.
- The asset (the curated dataset) compounds. A latecomer who turns on tracing today cannot reconstruct what your traffic taught you over six months.

Why this matters for AF specifically

- Pillar 1 (knowledge as strategic asset). The dataset literally is the asset. It is a curated, labeled record of what the agent has been asked to do and what good
answers look like. AF builders accumulate it just by running.
- Pillar 2 (iteration velocity). "Change → see outcome" only has teeth when there's a faithful evaluation set. The flywheel produces it.
- Pillar 3 (cost). A real dataset lets you prove that a cheaper model handles segment X — cost optimization grounded in evidence rather than guess.

Honest caveat

The loop only compounds if step 2 (sampling) and step 3 (annotation) actually happen. Without curation discipline, traces just pile up and the "dataset" is noise.
The flywheel claim is conditional on AF (or the product) shipping a real promotion + annotation workflow on top of MLflow's primitives, not just turning on tracing
