# Agent Foundry Documentation

Start with the [project README](../README.md) for Agent Foundry's current
positioning, install instructions, core concepts, and integration status.

Agent Foundry is in an OSS/framework pivot. Some docs are canonical and current;
others are implementation records or research notes that still need cleanup. This
index is the source of truth for where each kind of documentation belongs.

## Documentation Types

- **Guides**: task-oriented walkthroughs for builders using Agent Foundry.
- **Reference**: stable facts about APIs, protocols, configuration, and runtime
  behavior.
- **Architecture**: durable structure, principles, current-state analysis, and
  open decisions.
- **Design records**: implementation plans or subsystem designs. These may be
  historical unless marked current.
- **Strategy/research**: exploratory notes used to make project decisions. These
  are not product documentation.

## Guides

Use these when learning or building with Agent Foundry.

- [Getting started](guides/getting-started.md) — first typed process, validation,
  and execution. **Needs rewrite for the framework pivot.**
- [Extending Agent Foundry](guides/extending.md) — custom constructs, compilers,
  validators, executors, and providers. **Needs terminology cleanup.**
- [Agent containers](guides/agent-containers.md) — containerized agent execution.
  **Needs broader coverage as additional executor adapters are added.**

## Reference

Use these when checking concrete behavior or integration details.

- [Agent containers reference](reference/agent-containers.md) — current low-level
  container/protocol reference for the current Docker + Claude Code path.
- [AICall resilience reference](reference/ai-call-resilience.md) — retry,
  failover, timeout, custom executor, observability, and known gaps for model
  calls.
- [Evals reference](reference/evals.md) — typed eval models, runner boundary,
  registry, CLI, and API.
- [Public API policy](reference/public-api.md) — stable, experimental, and
  internal API tiers for the framework pivot.
- [Runtime accessors](reference/runtime.md) — run-scoped helpers for
  function/action code.

## Architecture

Use these to understand Agent Foundry's durable structure and unresolved design
questions.

- [Motivation and principles](architecture/motivation-and-principles.md) — why
  Agent Foundry exists and what it optimizes for. **Needs framework-language
  alignment.**

## Design

- [Checkpoint and resume contract](design/checkpoint-resume-contract.md) —
  framework-level contract for durable typed checkpoints and explicit resume
  planning.
- [Observability adapter design](design/observability-adapter-design.md) —
  vendor-neutral telemetry core and optional MLflow adapter.

Historical subsystem design records that still need disposition live in
[design/staged-for-processing/](design/staged-for-processing/). Read them as
implementation history rather than current user-facing guidance.
