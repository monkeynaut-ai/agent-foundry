# Codex Review Of Agent Foundry Platform

Review date: 2026-05-21

## Executive Summary

Agent Foundry has a strong foundation for a typed, local-first agent workflow runtime. Its best-developed parts are the Pydantic primitive model, LangGraph compilation path, container-backed Claude execution, lifecycle artifacts, MLflow/OpenTelemetry integration, and a broad unit test suite.

It is not yet ready to be treated as a production platform that multiple applications can rely on to define, run, and manage agentic systems at scale. The implementation is closer to a capable internal runtime/framework: it can run structured agent workflows, but important platform concerns remain incomplete or inconsistent.

The highest-priority issues are:

| Priority | Finding | Impact |
| --- | --- | --- |
| P0 | Human gates are compilation interrupts, not a complete durable human-task workflow. | Applications cannot yet rely on the platform for auditable pause, assignment, resume, or approval flows. |
| P0 | Runtime execution is in-process and file-backed, without a durable run store, queue, or recovery model. | Long-running, cross-process, multi-application operation is fragile. |
| P1 | Declared timeout fields are not enforced in agent or AI request execution paths. | A platform consumer can configure safety bounds that the runtime does not honor. |
| P1 | Summary generation appears to read `agent` while runtime events emit `agent_name`. | Run summaries can silently omit agent invocation statistics. |
| P1 | Prompts, streams, outputs, and generated instructions are persisted unredacted. | Sensitive user data, customer data, or secrets can leak into artifacts and logs. |
| P1 | Public docs and examples are stale relative to the implemented API. | New application teams will likely fail to onboard without reading source code. |
| P2 | Tool, MCP, environment, and volume policies are permissive and mostly caller-managed. | The platform lacks a clear capability policy boundary. |

The implementation is most credible today as:

- A controlled internal framework for single-team agent workflows.
- A local or CI-oriented execution substrate for typed agent experiments.
- A foundation for a platform, provided the team next invests in durable run management, human-task semantics, policy enforcement, and public API cleanup.

It is least ready today as:

- A multi-tenant agent platform.
- A hosted service boundary for untrusted applications.
- A production workflow engine for long-running human/agent systems.
- A stable external developer platform.

## System Model Observed

The current implementation centers on a typed primitive tree. A `PrimitivePlan` wraps a root primitive, validators check type compatibility, a compiler translates primitives into a LangGraph `StateGraph`, and `run_primitive_plan` executes the compiled graph inside an async Python process.

The main implemented primitive families are:

- `Sequence`, `Loop`, `Retry`, and `Conditional` for control flow.
- `FunctionAction` for Python callables.
- `AgentAction` for container-backed Claude Code execution.
- `GateAction` for graph interrupts.
- `AIRequest` for direct model-provider calls.

The main persistence boundary is the filesystem. Each run writes lifecycle JSONL, summary files, prompts, model streams, envelopes, structured outputs, collected files, and retained-container diagnostics when failures occur. There is no durable database-backed run model, scheduler, queue, worker pool, or application-level management API in the reviewed implementation.

## Findings By Dimension

### 1. Core Domain Model

This dimension evaluates whether the platform exposes a coherent model for defining agentic systems: agents, human tasks, scripted tasks, control flow, inputs, outputs, tools, and policies. A strong platform model should be expressive enough for real workflows while preserving type safety, validation, and clear ownership boundaries.

**Conclusion:** The implemented primitive model is clean and useful, but it is narrower than the platform story. It models executable workflow trees well; it does not yet model full systems, participants, durable human work, application ownership, tenancy, or capability policy as first-class platform entities.

**Strengths**

- Generic Pydantic primitives give the runtime a typed input/output contract.
- `Sequence` supports accumulated state flow rather than forcing exact adjacent type equality.
- `AgentAction`, `FunctionAction`, `GateAction`, `AIRequest`, and control-flow primitives cover the basic composition vocabulary.
- Validators provide early feedback for many type-shape errors.

**Risks**

- The deployed unit is effectively `PrimitivePlan(root=...)`, not a richer "agentic system" definition.
- Human tasks are represented weakly compared with agent and function work.
- `FunctionAction` is an unconstrained escape hatch; side effects, external calls, and data access are not declared.
- Agent names are not globally unique, and comments in the model acknowledge artifact/log collisions.
- Capability and role concepts appear in design material but are not implemented as a coherent current API.

**Readiness:** Good framework primitive layer; incomplete platform domain model.

**Confidence:** High.

### 2. Execution Model

This dimension evaluates how definitions become executable work: compilation, scheduling, concurrency, cancellation, retries, interruptions, and result validation. A strong execution model should make control-flow semantics explicit and should behave predictably under failure and long-running workloads.

**Conclusion:** The compile-and-run path is understandable and reasonably tested, but it is an in-process runtime rather than a durable execution engine. LangGraph is a good fit for local graph execution, but platform-grade scheduling, recovery, and interrupt/resume semantics are still missing.

**Strengths**

- `compile_runtime_plan` validates plans, derives a runtime state type, compiles nodes, and returns a LangGraph application.
- `run_primitive_plan` performs run bootstrap, context setup, cancellation wiring, graph invocation, final output validation, lifecycle emission, and cleanup.
- Agent actions are isolated into containers and produce structured outputs validated through Pydantic.
- `Retry` and `Conditional` have clear compiler behavior for common local workflows.

**Risks**

- Execution happens inside one async process; there is no durable scheduler or queue.
- LangGraph checkpointing is only lightly used for gates; normal `run_primitive_plan` invocation does not expose a complete resume protocol.
- Generic retry behavior is not surfaced as rich lifecycle metadata.
- Long-running work depends on process health and local filesystem availability.
- There is no platform-level concurrency, admission control, lease, or worker ownership model.

**Readiness:** Effective local executor; not yet a production workflow engine.

**Confidence:** High.

### 3. State And Memory

This dimension evaluates how state moves through a run, how intermediate artifacts are stored, and whether execution can be recovered, queried, or audited later. A strong platform should distinguish transient runtime state from durable business state and should offer clear retention and access semantics.

**Conclusion:** The filesystem artifact model is practical and debuggable, but it is not a durable platform state model. It supports local inspection well; it does not yet support robust recovery, query, retention policy, cross-process ownership, or application-level run management.

**Strengths**

- Per-run artifact directories are simple to inspect.
- Lifecycle JSONL is append-only and flushed per record.
- Agent turn artifacts include prompts, raw streams, envelopes, outputs, collected files, and diagnostics.
- Failed containers can be retained for forensics.

**Risks**

- There is no database or durable state store for run status, ownership, resumption, or indexing.
- Artifacts are written as raw local files without a policy boundary for sensitive contents.
- Run summaries are derived after execution rather than maintained as authoritative state.
- A process crash can leave artifacts and containers requiring manual interpretation.

**Readiness:** Good debugging artifact trail; insufficient platform state layer.

**Confidence:** High.

### 4. Human-In-The-Loop Support

This dimension evaluates whether the platform can represent, pause for, assign, resume, and audit human participation in agentic systems. A strong implementation should treat human work as first-class, durable, attributable, and policy-controlled.

**Conclusion:** Human-in-the-loop support is present but immature. The responder protocol can collect local clarifications and permission answers during an agent turn, while `GateAction` is not yet a complete human task abstraction.

**Strengths**

- `Responder` gives agent execution a structured way to ask clarification and permission questions.
- Responder prompts include agent name, invocation id, turn number, and request id.
- The stdin responder serializes interactive prompts and avoids blocking the event loop directly.

**Risks**

- `GateAction` compiles to a pass-through interrupt node but lacks a complete durable resume and human-task lifecycle.
- Permission responses are free-form text, not typed approve/deny/escalate decisions.
- Human identity, assignment, SLA, queueing, and audit trails are absent.
- There is no application-facing API for pending human work.
- Gate lifecycle enum values exist, but real gate-entered/gate-resumed behavior is not implemented in the main runner path.

**Readiness:** Useful local interaction protocol; not ready for managed human tasks.

**Confidence:** High.

### 5. Tool And Integration Safety

This dimension evaluates how external tools, MCP servers, containers, files, credentials, and model-facing capabilities are exposed and constrained. A strong platform should make capabilities explicit, least-privilege, reviewable, and enforceable.

**Conclusion:** The implementation has useful safety primitives, especially containerization and environment allowlisting, but policy remains mostly caller-managed. The current model would need stronger capability declarations and enforcement before accepting untrusted apps or broad organizational use.

**Strengths**

- The default environment allowlist is small and excludes common broad secrets.
- Containers drop most Linux capabilities and run agent work as a non-root user.
- Resource constraints exist for memory, CPU, and process count.
- MCP server settings are generated rather than left entirely ad hoc.
- File outputs declared through `AgentFilePath` are verified and snapshot into artifacts.

**Risks**

- `skip_permissions` can pass Claude Code's dangerous permission bypass flag.
- MCP permissions are wildcarded per server rather than scoped per tool.
- `extra_env` and `extra_volumes` provide broad caller-controlled escape hatches.
- Containers include `host.docker.internal` mapping, increasing host reachability.
- Network egress policy is not modeled as a first-class control.
- There is no unified capability registry that ties model prompts, tools, file access, and human approvals together.

**Readiness:** Reasonable controlled-run safeguards; incomplete platform policy layer.

**Confidence:** High.

### 6. API And Developer Experience

This dimension evaluates whether application teams can discover, understand, and use the platform without reverse-engineering internals. A strong platform API should be stable, documented, example-backed, and hard to misuse.

**Conclusion:** The source code exposes useful building blocks, but the developer experience is not yet coherent. Public exports, examples, docs, package metadata, and current runtime signatures are inconsistent.

**Strengths**

- The primitive API is readable once located.
- Orchestration exports `run_primitive_plan`.
- The tests provide many executable examples for maintainers.
- Pydantic validation gives developers structured error feedback.

**Risks**

- The root `agent_foundry` package exports nothing.
- `AIRequest` is implemented but not exported from `agent_foundry.primitives`.
- The README's authentication guidance is inconsistent with the container execution path.
- Draft docs show stale import paths and stale custom compiler signatures.
- The MLflow example fails at plan construction because `AgentAction.model` is required but omitted.
- `pyproject.toml` still has a template description and a very strict Python `==3.14.*` requirement.

**Readiness:** Usable by maintainers; rough for application developers.

**Confidence:** High.

### 7. Reliability Semantics

This dimension evaluates whether the platform makes reliability guarantees explicit: retries, timeouts, cancellation, idempotency, cleanup, and behavior under partial failure. A strong platform should avoid configuration fields that look enforced but are not.

**Conclusion:** The runtime has a number of pragmatic reliability features, but its guarantees are incomplete and sometimes misleading. The most important gap is that timeout fields are declared on primitives but do not appear to be enforced by the executor/provider paths.

**Strengths**

- Agent turns have one retry for retryable provider/API failures.
- Cancellation events are threaded through the run context and container execution.
- Failed containers can be retained for diagnosis.
- Final graph outputs are validated against the expected Pydantic output model.
- Registry shutdown attempts to clean up live containers.

**Risks**

- `AgentAction.timeout_seconds` and `AIRequest.timeout_seconds` are part of the model but not applied around real execution.
- Claude Code is invoked without an explicit max-turn bound.
- Generic `Retry` semantics are not accompanied by idempotency guidance or attempt-level lifecycle metadata.
- Cleanup behavior depends on local process shutdown and Docker availability.
- There is no durable lease or recovery story for work interrupted by host failure.

**Readiness:** Adequate for controlled local runs; reliability contract needs tightening.

**Confidence:** High.

### 8. Observability And Auditability

This dimension evaluates whether operators and application owners can understand what happened during a run, why decisions were made, and where failures occurred. A strong platform should provide correlated, queryable, redacted, and complete telemetry across agent, human, model, and tool activity.

**Conclusion:** Observability is one of the stronger areas, but it is still split between rich local artifacts and incomplete structured telemetry. The artifact trail is excellent for maintainers; the platform audit model is not yet complete.

**Strengths**

- Lifecycle JSONL records major run and agent events.
- Per-turn artifacts capture prompts, streams, envelopes, outputs, and collected files.
- OpenTelemetry span hooks exist for `AgentAction` and `AIRequest`.
- MLflow integration can create runs, log metrics, and attach artifacts.
- Telemetry configuration has a redaction policy for span attributes.

**Risks**

- Summary generation appears to use the wrong key for agent statistics.
- Composite primitives are not consistently represented as spans.
- `RunStats` fields such as span count, error count, and token totals are placeholders.
- Span helpers support model id and token usage, but those values are not consistently populated.
- Filesystem artifacts are not covered by the telemetry redaction policy.
- Human interactions are not represented as durable, attributable audit events.

**Readiness:** Strong local debugging; incomplete operational audit layer.

**Confidence:** High.

### 9. Evaluation And Testing

This dimension evaluates whether the test and evaluation strategy proves the platform works across unit, integration, live provider, benchmark, and example paths. A strong strategy should protect both maintainers and application teams from regressions in the actual user-facing workflows.

**Conclusion:** The non-integration test base is substantial and currently healthy. The main gaps are live/integration coverage, stale examples, and missing tests around several platform-critical semantics.

**Strengths**

- The non-integration suite passed during review: 789 tests.
- Ruff and Pyright passed during review.
- Tests cover primitives, compiler behavior, orchestration, responders, lifecycle, registry, telemetry, MLflow, evals, and archetype.
- The eval harness uses typed task suites and writes structured reports.
- Docker and live Claude integration tests exist, even though they were not run in this review.

**Risks**

- Integration tests require Docker and real Claude/OAuth state, so they are likely manual or environment-gated.
- `tests-evals` is outside the default pytest `testpaths` and must be run intentionally.
- At least one example fails before execution.
- Tests do not currently catch the summary `agent_name` mismatch.
- Tests do not appear to enforce timeout behavior, real gate resume, or artifact redaction.

**Readiness:** Strong maintainer unit coverage; incomplete release confidence for platform behavior.

**Confidence:** High for non-integration paths; medium for live paths because they were intentionally not run.

### 10. Security And Isolation

This dimension evaluates whether execution boundaries protect the host, applications, users, credentials, and generated artifacts. A strong platform should define a security model explicitly and should make unsafe choices visible and auditable.

**Conclusion:** The implementation takes meaningful steps toward isolation, but it does not yet have a complete platform security model. The most pressing issue is unredacted persistence of model-facing and model-generated data.

**Strengths**

- Containerized execution creates a concrete boundary around agent actions.
- The default environment allowlist avoids passing arbitrary host secrets.
- Containers run as a non-root user with selected group IDs.
- Workspace lockdown and GID behavior have integration tests.
- GitHub credentials are not passed by default.

**Risks**

- Raw prompts, streams, structured outputs, and collected files are persisted without redaction.
- Generated `CLAUDE.md` instructions are printed to container logs and snapshotted.
- `extra_env` can reintroduce sensitive credentials without a masking policy.
- Containers are not read-only and have host-gateway reachability.
- There is no tenant, application, user, or role-based authorization layer.
- No documented threat model defines what the platform is meant to defend against.

**Readiness:** Reasonable single-operator isolation; insufficient for multi-tenant or regulated use.

**Confidence:** High.

### 11. Extensibility

This dimension evaluates whether new primitives, providers, integrations, telemetry sinks, and execution backends can be added without destabilizing the core. A strong platform should expose narrow extension points with clear contracts and tests.

**Conclusion:** Extensibility exists but is still close to internal implementation details. The primitive validator/compiler registries are useful, while custom compilers and provider extension paths need clearer public contracts.

**Strengths**

- Validators and compilers are registry-based.
- `RunContext` exposes contextual services without requiring global parameters everywhere.
- AI model providers can be registered.
- Hook and telemetry provider interfaces allow lifecycle integrations.
- MLflow is implemented as an adapter rather than hard-coded into the runner.

**Risks**

- `compile_runtime_plan` is explicitly marked as not public API, but custom primitives need compiler hooks.
- Draft documentation for custom compilers is stale.
- `RunContext.extras` is flexible but can become an untyped dependency channel.
- Primitive extension contracts are not yet documented as stable.
- Provider/runtime boundaries are not packaged as a clean plugin API.

**Readiness:** Good internal extensibility; not yet a supported external extension platform.

**Confidence:** Medium-high.

### 12. Operational Readiness

This dimension evaluates whether the platform can be deployed, monitored, upgraded, cleaned up, and supported by an operations team. A strong platform should have clear runtime dependencies, failure modes, cleanup tools, and production controls.

**Conclusion:** Operational readiness is limited to local or controlled environments. The implementation lacks the service-level components expected from a managed platform.

**Strengths**

- Artifacts are local and inspectable.
- Run summaries and inspect scripts help with failure diagnosis.
- Container cleanup and retention behavior are explicit.
- The MLflow adapter has lifecycle hooks for external tracking.

**Risks**

- There is no server/API layer for applications to submit, list, cancel, or resume runs.
- There is no queue, worker pool, scheduler, or backpressure mechanism.
- There is no run database, migration plan, or retention/compaction policy.
- Retained failed containers can accumulate operational debt.
- Strict Python versioning may complicate installation.
- Runtime dependencies include test tooling such as `pytest`.

**Readiness:** Local operational tooling is useful; hosted platform operations are not present.

**Confidence:** High.

### 13. Architectural Consistency

This dimension evaluates whether implementation, docs, tests, examples, and design documents describe the same architecture. A strong platform should not require users to guess which layer is current.

**Conclusion:** The implementation has moved ahead of several docs and examples. This creates friction because the most trustworthy description of the platform is now the source and tests rather than the public-facing material.

**Strengths**

- The source code has a coherent current architecture around primitives, compilation, and orchestration.
- Tests largely reflect the actual implementation.
- Design documents show useful future intent.

**Risks**

- Older architecture documents describe participants, roles, capabilities, and graph wiring concepts that are not the current implemented API.
- README authentication guidance conflicts with the current container default environment flow.
- Usage docs show stale imports and custom compiler signatures.
- Examples are not all kept green.

**Readiness:** Internally understandable; externally confusing.

**Confidence:** High.

### 14. Product Fit

This dimension evaluates whether the implementation matches the product claim: a platform that applications use to define, run, and manage agentic systems. A strong fit requires both a programmable workflow runtime and management surfaces for applications and operators.

**Conclusion:** The implementation fits the "define and run" portion for controlled workflows, especially agent and scripted tasks. It is weaker on "manage": durable run lifecycle, human work management, application-level APIs, policy administration, and operational controls are not yet platform-grade.

**Strengths**

- Applications can define typed workflows as Python objects.
- Agent, AI request, function, and control-flow primitives can be composed.
- Runs produce useful artifacts for debugging and evaluation.
- MLflow integration supports experiment-style tracking.

**Risks**

- There is no application-facing management plane.
- There is no stable public domain model for systems, apps, users, teams, policies, or capabilities.
- Human tasks and approvals are not first-class managed work items.
- Production concerns are mostly left to embedding applications.

**Readiness:** Promising runtime foundation; not yet a complete application platform.

**Confidence:** High.

## Cross-Cutting Findings

### A. The Runtime Is Stronger Than The Platform Boundary

The codebase has credible runtime mechanics, especially around primitive compilation and container execution. The platform boundary is less mature: no durable run store, no management API, no tenancy model, no capability administration, and no complete human work queue.

### B. Several Declared Contracts Are Ahead Of Enforcement

Fields and concepts such as timeouts, gates, telemetry stats, and capability-oriented docs imply stronger guarantees than the implementation currently provides. These should either be implemented or made explicitly experimental to avoid misleading platform consumers.

### C. Local Debuggability Is Excellent, But Sensitive By Default

Persisting prompts, streams, envelopes, outputs, collected files, logs, and generated instructions makes failures easy to inspect. The same design can leak sensitive information unless artifact redaction, retention, and access controls are added.

### D. The Tests Prove The Maintainer Path Better Than The Consumer Path

Unit coverage is strong and passing. Consumer-facing confidence is weaker because examples are stale, integration tests require special live environments, and several platform-level contracts are not covered.

### E. Documentation Debt Is Now A Product Risk

When README, docs, examples, and implementation disagree, application teams will either fail early or build against internal details. This is especially risky if the goal is a platform used by multiple application teams.

## Platform Readiness Assessment

| Area | Assessment |
| --- | --- |
| Typed workflow definition | Strong for current primitive set |
| Local execution | Strong |
| Agent container execution | Promising, with safety gaps |
| Direct AI requests | Present but less integrated |
| Human tasks | Incomplete |
| Durable run management | Missing |
| Multi-application management | Missing |
| Multi-tenant security | Missing |
| Observability | Strong local artifacts; incomplete telemetry/audit |
| Evaluation | Good foundation |
| Public API and docs | Needs cleanup |
| Production operations | Early |

Overall readiness: **internal alpha platform foundation**.

Recommended use today: controlled internal workflows, local/CI agent experiments, demos that tolerate manual operations, and continued platform development.

Not recommended today: untrusted workloads, multi-tenant hosting, external developer onboarding, regulated data flows, or production workflows requiring durable human approvals and recovery.

## Risk Register

| ID | Risk | Severity | Likelihood | Evidence | Recommended Action |
| --- | --- | --- | --- | --- | --- |
| R1 | Gate/human-task workflow is incomplete. | High | High | `GateAction` compiles to interrupt/pass-through; no complete runner resume API. | Design durable human task model with pending-task store, assignment, resume, identity, and audit events. |
| R2 | Runtime has no durable run store or queue. | High | High | Execution is async in-process with filesystem artifacts. | Introduce run database, state machine, scheduler/worker model, leases, and recovery protocol. |
| R3 | Timeout fields are not enforced. | High | Medium | `timeout_seconds` appears in models but not executor/provider enforcement paths. | Apply async timeouts around agent turns and AI provider calls; add tests. |
| R4 | Summary agent stats can be wrong. | Medium | High | Runtime emits `agent_name`; summary reads `agent` for stats. | Normalize lifecycle schema and update summary/tests. |
| R5 | Artifacts persist sensitive data unredacted. | High | High | Prompt, stream, output, and instruction artifacts are stored raw. | Add artifact redaction, retention policy, sensitivity labeling, and access controls. |
| R6 | Docs/examples are stale. | Medium | High | README auth mismatch; draft docs stale; MLflow example fails. | Establish docs-as-tests and CI smoke tests for examples. |
| R7 | Tool and MCP permissions are broad. | Medium | Medium | MCP permissions are wildcard per server; `extra_env`/`extra_volumes` are broad. | Add capability manifests, policy validation, and least-privilege MCP tool grants. |
| R8 | Live/integration paths are not continuously proven. | Medium | Medium | Integration tests require Docker/OAuth/live services and were not run here. | Add scheduled/live CI lane and fast smoke tests with recorded or fake provider paths. |
| R9 | Auth story is inconsistent. | Medium | High | README documents API key container auth; current default container env path uses OAuth. | Split and document AgentAction vs AIRequest auth, or implement both paths consistently. |
| R10 | Operational cleanup can become manual. | Medium | Medium | Failed containers may be retained; no retention manager or run index. | Add cleanup commands, retention policy, and operator dashboards. |

## Recommended Roadmap

### Phase 1: Make Current Runtime Contracts True

1. Enforce `timeout_seconds` for `AgentAction` and `AIRequest`.
2. Fix lifecycle summary key mismatch and define a versioned lifecycle event schema.
3. Make all examples construct and run at least to a fake/smoke boundary in CI.
4. Update README and usage docs to match the implemented public API.
5. Export a coherent public API from `agent_foundry`.
6. Add tests for gate behavior, timeout behavior, summary generation, auth guidance assumptions, and artifact redaction.

### Phase 2: Establish Platform Safety And Policy

1. Define a threat model for local, single-tenant, and future multi-tenant use.
2. Add artifact redaction and retention controls.
3. Replace broad `extra_env`/`extra_volumes` patterns with reviewed capability manifests.
4. Make MCP permissions per-tool where possible.
5. Add policy validation before a plan can run.
6. Make dangerous permissions visible in lifecycle events and summaries.

### Phase 3: Build Durable Management Semantics

1. Introduce a durable run store with run status, ownership, inputs, outputs, lifecycle pointers, and artifact pointers.
2. Add a scheduler/worker model with leases, cancellation, retry ownership, and crash recovery.
3. Define durable gate/human-task records with assignment, identity, decisions, comments, and resume tokens.
4. Expose application-facing APIs to submit, inspect, cancel, resume, and list runs.
5. Add retention, cleanup, and migration tooling.

### Phase 4: Productize The Developer Platform

1. Stabilize the public primitive/provider/compiler extension API.
2. Publish versioned docs and examples aligned with tests.
3. Add compatibility tests for common application integration patterns.
4. Provide an operator guide, security guide, and incident/debugging guide.
5. Add release gates that include docs, examples, unit tests, integration smoke tests, type checks, and lint.

## Testing And Verification Plan

The following verification should become part of the regular release process:

| Category | Required Checks |
| --- | --- |
| Unit and type checks | `pytest`, eval tests, ruff, pyright |
| Example checks | Construct every example plan; run examples with fake executors where possible |
| Live integration | Docker image build, live Claude/OAuth smoke, MCP server smoke, workspace permission tests |
| Reliability | Timeout enforcement, cancellation, retry exhaustion, cleanup on failure |
| Human tasks | Gate creation, pending state, resume, identity audit, denial/escalation |
| Security | Env allowlist, secret masking, artifact redaction, extra volume policy, network policy |
| Observability | Lifecycle schema validation, summary correctness, OTel spans, MLflow artifacts |
| Operations | Retained container cleanup, run retention, interrupted process recovery |

## Appendix A: Evidence Notes

### Repository Shape

- `src/agent_foundry/primitives/models.py` contains the core generic primitive model.
- `src/agent_foundry/primitives/ai_request.py` contains direct AI request primitives.
- `src/agent_foundry/compiler/primitive_compiler.py` contains the LangGraph compiler.
- `src/agent_foundry/orchestration/runner.py` contains the primary run entrypoint.
- `src/agent_foundry/orchestration/container_executor.py` contains the Claude container turn executor.
- `src/agent_foundry/agents/lifecycle.py` contains container lifecycle and Docker safety settings.
- `src/agent_foundry/responders` contains local human response protocols.
- `src/agent_foundry/telemetry` and `src/agent_foundry/mlflow_adapter` contain observability integrations.
- `src/agent_foundry/evals` contains evaluation harness support.

### Validation And Compilation

- Primitive validation is registry-based; unknown primitives raise an error.
- `Sequence` validation accumulates fields through each step.
- `Retry` and `Conditional` use stricter input/output compatibility checks.
- Loop body compatibility is deferred to the compiler.
- Gates are collected during compilation and passed as `interrupt_before` nodes.

### Runtime And Persistence

- `run_primitive_plan` creates a run id, bootstraps artifacts, creates a lifecycle writer, container registry, and run context, compiles the graph, invokes it, validates output, writes terminal lifecycle events, shuts down containers, writes a summary, and fires hooks.
- Per-run artifacts include `lifecycle.jsonl`, `summary.txt`, `inspect-workspace.sh`, agent prompt files, stream JSONL, envelopes, structured outputs, collected files, container logs, Docker inspect output, cgroup memory data, and retained-container scripts.
- Lifecycle writes are flushed per event.

### Human Interaction

- `Responder` supports clarification and permission requests during agent execution.
- The stdin responder collects free-form answers.
- Gate actions do not yet form a complete durable human task workflow.

### Container Execution

- Agent execution runs Claude Code in Docker with structured output schema support.
- The executor captures session ids and supports reuse/resume policy.
- API retry is limited to one retry for selected retryable statuses and transport failures.
- `AgentFilePath` outputs are verified and copied into artifacts.
- Failed container diagnostics are collected.

### Security And Isolation

- Default environment allowlist includes `CLAUDE_CODE_OAUTH_TOKEN`, not arbitrary host secrets.
- Tests assert `ANTHROPIC_API_KEY` is not in the default container environment allowlist.
- Containers drop most Linux capabilities and run as the `claude` user.
- Containers are not read-only and include host-gateway mapping.
- Prompts, streams, outputs, and generated instructions are persisted without redaction.

### API And Documentation

- `agent_foundry.__init__` is empty.
- `agent_foundry.primitives.__init__` does not export `AIRequest`.
- `agent_foundry.orchestration.__init__` exports `run_primitive_plan`.
- Draft docs show stale imports and compiler signatures.
- README auth guidance says API key usage is supported for Claude Code containers, but the implemented default container environment path centers on `CLAUDE_CODE_OAUTH_TOKEN`.
- `examples/mlflow_demo/main.py` failed plan construction during review because `AgentAction.model` is required.

### Observability

- Agent actions and AI requests emit telemetry spans.
- Composite control-flow primitives are not consistently represented as spans.
- `RunStats` token/span/error totals are placeholders.
- MLflow integration logs metrics and artifacts through lifecycle hooks.
- Summary generation appears to read `agent`, while runtime events emit `agent_name`.

## Appendix B: Verification Performed

These commands were run during the review:

```bash
uv run pytest tests/agent_foundry tests-evals/agent_foundry -m 'not integration and not benchmark' --maxfail=1
```

Result: 640 passed.

```bash
uv run pytest tests tests-evals -m 'not integration and not benchmark' --maxfail=1
```

Result: 789 passed.

```bash
uv run ruff check src tests tests-evals
```

Result: all checks passed.

```bash
uv run pyright
```

Result: 0 errors, 0 warnings, 0 informations. This required escalated execution because the sandbox could not read part of the local uv cache.

```bash
uv run python -c "from examples.mlflow_demo.main import build_plan; build_plan()"
```

Result: failed with a Pydantic validation error because `AgentAction[TicketInput, TicketOutput]` requires `model`.

## Appendix C: Verification Not Performed

The Docker/OAuth/live Claude integration tests were not run as part of this review. They require Docker image/runtime availability and real provider credentials, and may incur external service usage.

Benchmark tests were not run because the review focused on correctness, architecture, and platform readiness rather than performance characterization.

## Appendix D: Publication Rubric Applied

Each major section was considered ready for publication when it met these criteria:

- The conclusion was stated before the supporting detail.
- The conclusion was tied to observed implementation evidence.
- The section distinguished implemented behavior from design intent.
- The section identified both strengths and risks.
- Recommendations were actionable and proportionate to platform maturity.
- Evidence that would interrupt readability was moved to an appendix.
- Confidence was stated when live or integration coverage was incomplete.

