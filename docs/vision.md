# Agent Foundry Vision

Agent Foundry exists to make learning and experimentation in agentic systems
faster without losing structure, typed boundaries, or operational traceability.

We are in the early days of using AI and agentic systems. Builders are still learning which
instructions work, how memory should be managed, what topology fits a use case,
which models justify their cost, where humans should stay in the loop, how
agent behavior should be evaluated, and so on.

Agent Foundry gives those experiments a stable frame: declare the durable shape
of the process once, then vary prompts, models, tools, memory strategies, agent
harnesses, execution backends, and observability systems behind explicit seams.

## What We Believe

- **Experimentation is the core workflow.** The framework should make it cheap
  to change the volatile parts of an agentic system while preserving a stable
  process contract for comparison and measurement.
- **Typed boundaries matter.** Dynamic agent behavior is easier to reason about
  when process inputs, outputs, gates, retries, model calls, and agent actions
  cross declared Pydantic model boundaries.
- **Adapter seams reduce lock-in.** Workflow engines, agent harnesses, model
  providers, tools, containers, and observability systems should be replaceable
  implementation choices where feasible.
- **Operational evidence is part of the system.** Runs should produce lifecycle
  events, summaries, traces, and typed outcomes so builders can inspect what
  happened and improve the next experiment.
- **Safe defaults are non-negotiable.** Absence of configuration must not grant
  authority. Access, tools, environment, and execution behavior should be
  explicit.

## Current Focus

The mature core is a bounded typed process framework:

- composable, declarative constructs
- Pydantic input/output contracts
- graph validation
- LangGraph-backed execution with a seam for additional frameworks
- function, model-call, gate, and agent-action leaves
- lifecycle events and run outcomes
- initial container, Claude Code, OpenTelemetry, MLflow, and eval integrations

The broader adapter ecosystem is a work in progress. More workflow-engine,
agent-harness, model-provider, tool, container, observability, and eval adapters
need to be designed, built, and validated over time.

## Builder Journey

In the first hour, a builder should be able to define typed state models,
compose a small process from constructs, validate it, and run it.

In the first week, a builder should be able to replace functions with model
calls or agent actions, add retries or human gates, capture run evidence, and
compare variants.

Over time, a builder should be able to migrate pieces of the system between
providers, harnesses, and execution backends without rewriting the process
contract from scratch.

## Non-Goals

Agent Foundry is not:

- a hosted platform
- a general-purpose workflow engine
- only a model provider abstraction
- a replacement for every agent framework
- a promise of backend portability before adapters exist
