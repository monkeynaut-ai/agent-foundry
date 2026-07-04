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
  **Needs repair against current paths and scripts.**

## Reference

Use these when checking concrete behavior or integration details.

- [Agent containers reference](reference/agent-containers.md) — current low-level
  container/protocol reference for the current Docker + Claude Code path.
- [Evals reference](reference/evals.md) — typed eval models, runner boundary,
  registry, CLI, and API.
- [Archived reference](archive/reference/) — legacy container notes, Claude CLI
  snapshots, and instruction-layering notes.

## Architecture

Use these to understand Agent Foundry's durable structure and unresolved design
questions.

- [Motivation and principles](architecture/motivation-and-principles.md) — why
  Agent Foundry exists and what it optimizes for. **Needs framework-language
  alignment.**
- [Current architecture](architecture/agent-foundry-architecture.md) — as-built
  architecture, realized core, gaps, and open questions.
- [Ontology](architecture/agent-foundry-ontology.md) — future-facing conceptual
  vocabulary for System, Process, Construct, Run, Topology, Participant, and
  Role. **Read as conceptual, not fully implemented.**
- [Open decisions](architecture/agent-foundry-open-decisions.md) — unresolved
  architectural decisions.

Exploratory architecture/research notes are archived here:

- [Value lever exploration](archive/research/value-lever-exploration.md)
- [Agent memory landscape research](archive/research/research-agent-memory-landscape.md)

## Design Records

Historical subsystem design records live in [design/archive/](design/archive/).
They cover AI-call resilience, telemetry, evals, container permissions, executor
failure handling, system resilience, and the Codex agent path. Read them as
implementation history rather than current user-facing guidance.

## Strategy

- [Framework positioning](archive/strategy/framework-positioning.md) —
  positioning memo used during the OSS/framework pivot. The README now owns the
  public positioning.

## Cleanup Roadmap

1. Rewrite [Getting started](guides/getting-started.md) around the current README
   story and a minimal runnable process.
2. Align [CONTRIBUTING.md](../CONTRIBUTING.md) with the framework/adapters
   language.
3. Keep public terminology aligned across guides and architecture:
   "framework", "application", "adapter", and "integration" are the preferred
   terms.
4. Continue separating generic container behavior from Claude-specific adapter
   details as new agent executors are added.
5. Continue pruning archived research and design records when they stop being
   useful.
6. Add status headers to any design records that move back into active docs.
7. Add markdown link checking so stale references do not return.
