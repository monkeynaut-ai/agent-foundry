# Agent Foundry: Motivation & Principles

This is the root document of the architecture set. It states why Agent Foundry
exists, what it optimizes for, and which principles should guide structural
decisions.

Agent Foundry is currently best understood as a typed, boundary-enforced
framework for declaring and running agentic systems. It provides a stable
process contract layer and adapter seams for workflow engines, agent harnesses,
model providers, tools, execution substrates, and observability backends.

The adapter ecosystem is a work in progress. The current code has a mature
typed process core and several initial integrations; broader backend portability
requires additional adapters and shared contract tests.

## Purpose

Agent Foundry helps builders experiment with agentic systems without rebuilding
the whole system each time. Applications compose typed constructs into runnable
processes; Agent Foundry validates state boundaries, compiles and runs the
process, records lifecycle evidence, and delegates volatile implementation
choices to explicit seams.

## Goals

### G1 — Make Agentic Experimentation Fast

LLMs and systems of agents are new. The best designs are still being discovered
through iteration. Agent Foundry should shorten the cycle between "I want to try
a change" and "I can compare the result."

**Cost we accept:** prompts, instructions, schema descriptions, response
channels, executors, models, harnesses, and providers remain configurable fields
or callables rather than hidden framework choices. This creates more surface
area, but it keeps experiments cheap.

### G2 — Keep Dynamic Systems Understandable

Agentic systems can become opaque when state, tools, callbacks, model behavior,
and retries are scattered through ad hoc code. Agent Foundry should preserve a
typed process frame around dynamic behavior.

**Cost we accept:** the framework validates boundaries, records lifecycle
events, and maintains explicit constructs even when a hand-written loop would
be shorter for a single prototype.

### G3 — Reduce Lock-In Where Feasible

Builders should be able to change models, providers, agent harnesses,
observability systems, and eventually workflow engines without rewriting the
durable process contract.

**Cost we accept:** backend-specific features must live behind adapters or be
marked as non-portable escape hatches. Interchangeability must be validated, not
assumed.

## Non-Goals

- **Not a hosted platform.** Agent Foundry is framework code applications use;
  it is not a managed service.
- **Not a general-purpose workflow engine.** The control-flow constructs are
  useful beyond agents, but Agent Foundry is optimized for agentic systems.
- **Not only a model provider abstraction.** Model calls are one leaf capability,
  not the whole framework.
- **Not a replacement for every agent framework.** Agent harnesses can sit behind
  Agent Foundry actions where that is useful.
- **Not a portability promise before adapters exist.** The seams are the
  strategy; adapters and contract tests make the strategy real.

## Decision Rule

When a design choice makes experimentation easier for applications but harder
inside the framework core, favor the application if the choice preserves typed
boundaries, explicit authority, and inspectable run evidence.

## Principles

- **Declarative process contracts.** A construct declaration is the
  authoritative specification of what a step does and how it runs.
- **Typed boundaries.** Public APIs and construct boundaries use Pydantic models.
  Validation happens at each boundary against the declared contract.
- **Safe by default.** Absence of configuration must not grant authority. Access,
  tools, environment, and execution behavior should be explicit.
- **Adapter seams over lock-in.** Provider-, harness-, engine-, tool-, and
  observability-specific details belong behind adapters. Escape hatches are
  allowed, but should be marked non-portable.
- **Extensibility via registries.** New construct types and validators register
  themselves. Unknown types fail loudly rather than falling back silently.
- **Composition over inheritance for state.** State models compose by fields and
  exact boundary contracts, not subclass hierarchies.
- **Evidence is part of execution.** Runs should produce lifecycle events,
  summaries, traces, and typed outcomes that make experiments comparable.
