# Agent Foundry: Motivation & Principles

This is the root document of the architecture set. It states **why Agent Foundry
exists** and **what it optimizes for** — the durable goals, non-goals, and the
decision rule that arbitrate every structural choice below it.

It is the thing other documents cite:

- [product-requirements.md](product-requirements.md) derives forces from these goals.
- [agent-foundry-architecture.md](agent-foundry-architecture.md) justifies structure against those forces.
- [agent-foundry-ontology.md](agent-foundry-ontology.md) supplies vocabulary — it is a coherence check, not a motivation.

This document should change rarely. If a goal here shifts, expect downstream
documents to move with it.

## Purpose

Agent Foundry is a **platform for building agentic systems**. Products (such as
Archipelago) compose typed constructs into runnable processes; the platform
handles the shared machinery — compilation, execution, container lifecycle,
protocol handling, structured output, lockdown, state flow, observability,
recovery — so products don't rebuild it.

## Goals

Two goals, each stated with the cost it commits us to. A goal earns its place
only if we would actually pay that cost — otherwise it's a platitude that
decides nothing.

### G1 — Accelerate building high-quality agentic systems

Agentic systems share a large body of infrastructure. Building a new one should
mean *composing constructs and declaring behavior*, not reimplementing
execution. Hardening, testing, and security fixes are centralized: an
improvement in one place benefits every product.

**Cost we accept:** the platform may become more complex,
indirect, and abstract so that product code stays simple. We push complexity
down into the platform even when a product-local shortcut would be easier *for
that one product*.

### G2 — Make experimentation fast

LLMs and systems of agents are new; the best designs are unknown and will be
found by iterating through experiments. Every capability is shaped by shortening
the cycle between "I want to try a change" and "I can see the outcome."

**Cost we accept:** the things products change most often — prompts,
instructions, schema descriptions, response channels, executors, models — are
swappable callable fields or data on the construct, changeable in one line
without touching framework code. We accept the added configurability surface and
late binding this creates, because a hardwired version that's faster to read is
slower to experiment with.

### When G1 and G2 tension

Hardening (G1) and rapid change (G2) can pull apart — more safety machinery can
slow iteration; more swap points can widen the surface to harden. The decision
rule and the safe-by-default stance arbitrate: we keep changes cheap, but never
by making a misconfiguration silently grant authority.

## Non-goals

> **Status: proposed — confirm or correct.** Non-goals constrain the
> architecture as much as goals; these are drafted from the current stance and
> need an explicit decision.

- **N1 — Not a general-purpose workflow engine.** The control-flow constructs
  are general, but the platform is motivated by and optimized for *agentic*
  systems. We do not chase parity with generic automation/orchestration tools.
- **N2 — Not optimizing single-run latency or throughput** at the expense of
  iteration speed, clarity, or safety. Performance work happens where it serves
  the goals, not as an end in itself.
- **N3 — Primarily a substrate, not a hosted end-user product** — but *not* a
  blanket ban on presentation. Agent Foundry's center of gravity is the platform
  products build on. However, where rendering or presentation of information
  (e.g. task-fit visualization at the human-interaction boundary) is where a
  value lever's payoff actually lives, AF may own that surface. The test is
  value, not category: own presentation when it carries the differentiation,
  not by default.
- **N4 — Not committed to a specific execution engine.** The engine (LangGraph
  today) is an encapsulated implementation detail and must remain replaceable.
- **N5 — Not making product decisions through platform defaults.** Where a
  choice carries product meaning, the platform offers options and the product
  must choose; the platform does not pick for it.

## Decision rule

> When a design choice makes things easier for products (composing, extending,
> experimenting) but harder inside the platform (more indirection, more dispatch
> logic, more runtime work), **favor the product. Push complexity into the
> platform, not onto products.**

This is the tiebreaker when goals, principles, or requirements contend.

## Principles (durable stances)

These are stances that follow from the goals and hold across the whole platform.
They are *values*, not structural designs; the concrete structural commitments
they imply (the construct tree, accumulated state, the compiler/validator
registries, typed boundaries) are recorded as decisions in
[agent-foundry-architecture.md](agent-foundry-architecture.md).

- **Platform, not a library.** Products build their own construct types, action
  variants, and participant implementations on top. Every API surface is
  designed for extension. *(serves G1, G2)*
- **Declarative.** A product's construct declaration is the complete,
  authoritative specification of what a construct does and how it runs. The
  platform executes what's declared; it does not inject product behavior through
  defaults. *(serves G2 — the declaration is the unit you experiment on and,
  later, version and grade)*
- **Safe by default.** For any field where absence could mean "more access,"
  absence means *less* access; the product opts in to each grant. Where a choice
  carries semantic weight, there is no default — the product must choose.
  Misconfiguration fails loudly and locally, never as a silent grant. *(serves
  G1; arbitrates the G1/G2 tension)*
- **Strict typing at boundaries.** Public APIs and inter-construct state are
  typed models, not raw dicts or string-keyed bags. Validation happens at each
  boundary against the declared contract. *(serves G1)*
- **Extensibility via registries.** New construct types, participants, and
  providers register themselves; dispatch is by registry lookup, and unknown
  types fail loudly rather than falling back silently. *(serves G1, G2)*

## Relationship to the rest of the architecture set

Motivation flows downhill: **goals + decision rule → product requirements
(forces) → architecture decisions → (described with) ontology vocabulary**, with
the ontology fed back as a coherence test. Each architectural decision and each
open question should trace to a force, and each force to a goal here. A "gap"
is something a force demands that no structure yet answers — never merely an
empty slot in a model.
