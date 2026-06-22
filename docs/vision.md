# Agent Foundry Vision

## Context

LLMs and agentic systems are new. Best practices for using LLMs, designing agent architectures, and building products around them are being discovered — not inherited from prior art. Our understanding of the problems and frictions is evolving. This document captures what we believe today, how we think builders experience the platform, and what we're still figuring out. It is a living document; sections will be revised as we learn.

## Who This Is For

Builders who want to rapidly create, and continually improve, high-quality agentic systems that bend the value curve up — accelerating how fast they deliver value through AI and AI agents.

These builders are optimizing for:

- Speed from idea to working system
- Iteration velocity — change something, see the outcome, learn
- Quality that doesn't require a second "hardening" project after the prototype

## What We Believe

Convictions strong enough to build on. All are subject to revision as we learn.

- **A high-quality foundation is worth building on.** Resilient, stable, and
  self-healing, with a full audit trail and tools for investigating what happened.
- **Complete control over the agent execution environment** is an advantage — running
  agents in containers, headless, with streaming output.
- **Always be capturing data.** Streaming agent output (assistant messages) lets us gauge
  how faithfully an agent follows its instructions, and feeds continuous improvement.
- **Knowledge is a strategic asset.** Accelerate learning; always look for ways to learn.
- **Prepare for rising LLM costs.** Build mitigations into the platform — e.g. optional
  model/provider switch logic for outages and cost control.

## Principles

- hide LangChain, LangGraph, MLflow
- constructs to simplify defining topology
- composability
- strict typing
- standardize tool calling - correctly interpret tool calls, and argument structure, from any model

<!-- Format: **Belief.** Rationale. -->

## Builder Journey

How a builder experiences Agent Foundry over time. This section is the lens for evaluating everything else — if a belief, a capability, or a design rule doesn't show up in the builder's actual experience, it's either aspirational or wrong.

### First Hour

<!-- What does a builder get out of the box? What can they stand up immediately? -->

### First Week

<!-- How do they extend, customize, experiment? What do they learn about the platform? -->

### Ongoing

<!-- How does the platform support continuous improvement? What gets better over time? -->

## Capability Rings

Each ring depends on the one inside it. For each: what exists today, what's next, and what's speculative.

### Core

The execution engine — constructs, compilation, state management, typing.

<!-- Exists: ... -->
<!-- Next: ... -->
<!-- Speculative: ... -->

### Platform Services

Value-added capabilities the platform provides to builders — memory, knowledge, data sources, communication channels.

<!-- Exists: ... -->
<!-- Next: ... -->
<!-- Speculative: ... -->

### Product Surface

What end-users of products built on Agent Foundry see — UI widgets per node, admin and monitoring UX.

<!-- Exists: ... -->
<!-- Next: ... -->
<!-- Speculative: ... -->

### Ecosystem

Extension points, registries, community-contributed constructs and agents.

<!-- Exists: ... -->
<!-- Next: ... -->
<!-- Speculative: ... -->

## Design Philosophy

Decision rules and tradeoffs that guide choices when the path isn't obvious.

<!-- Format: **Rule.** When it applies. Why. -->

## Ideas We Are Pondering

Frontiers we're actively exploring. Not gaps to fill — questions to investigate. As we learn, items here may become beliefs, capabilities, or get discarded.

- dynamic agent instructions, customize for each job
- enable simple and reactive changes to domain models
  - customized instructions per run, context size control, targeted focus, less rework (noise to correct later)
  - mitigation for future increases in llm inference costs

<!-- Format: **Question or idea.** What we're curious about. What would change if we found an answer. -->
