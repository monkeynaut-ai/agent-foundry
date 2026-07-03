# Agent Foundry Ontology: System, Process, Construct, Run

Agent Foundry builds, runs, and manages systems: it composes a system's definition, executes its processes, and operates them over their lifetime — lifecycle, resilience, observability, and audit. A system offers a catalog of **processes**; a process is a runnable definition built from **constructs**; each execution of a process is a **run**. These concepts form the platform's conceptual model. The model is independent of any execution engine — the engine that actually runs a process is an implementation detail the platform deliberately keeps hidden.

## The layered model

``` text
System      the deployment/product — offers a catalog of Processes, holds what they share
  └─ Process      a defined, runnable thing — topology-agnostic, lifespan-agnostic
       ├─ Topology     how its Constructs coordinate (graph today; router, blackboard later)
       └─ Construct    the composable unit a Process is built from
  └─ Run        one execution of a Process — triggered by API, app, or CLI; many run concurrently
```

Cardinality: a System offers **many** Processes; a Process has **many** concurrent Runs; each Run is bound to **exactly one** Process.

## Core Concepts

### System

A system is the unit of deployment. It offers a catalog of processes and owns what those processes share — the registry of which processes exist, their versioning, and cross-cutting concerns (shared knowledge stores, authentication, resources, triggers). A system is not itself runnable; it is the container and registry from which a run selects a process.

Archipelago is a system. A knowledge-management deployment is a system. Each is built on Agent Foundry but defines its own processes and the resources they share.

### Process

A process is the defined, runnable thing. It is the artifact a run enacts.

The Process *concept* is deliberately neutral on two axes — each individual process commits to one value of each:

- **Topology** — the platform does not privilege a single structural paradigm; the concept admits a graph (today), an agent-router, a blackboard, and others. Each process declares the one topology it uses (see Topology).
- **Lifespan** — the platform assumes no lifespan; a process may be a bounded job that completes or an indefinite standing behavior that never does. Each process is one or the other.

A process declares:

- **Constructs**: the units it is built from
- **Topology**: how those constructs coordinate
- **Entry point**: where a run begins
- **Contract**: the typed input it requires and output it produces

**Examples**: "implement a feature" is a bounded process — it terminates when the feature is built. "Continuously pull from changelogs and news sources, process articles, update a knowledge base, and notify a user when something noteworthy appears" is an unbounded process — it has no terminal goal. Both are processes; they differ in lifespan, not in kind.

### Topology

A topology is the structural paradigm by which a process's constructs coordinate. Today Agent Foundry implements one topology — a **graph** of constructs. Other topologies are anticipated (e.g. an agent-router that decides structure at runtime, or a blackboard with a shared store and a controller). Topology is a property of a process; the process name and contract do not change when the topology does, and the underlying execution engine is never exposed.

### Construct

A construct is the composable unit a process is built from. Constructs come in two categories, named by qualifier rather than by separate nouns:

- **Control-flow constructs** express the process's structure: Sequence, Loop, Retry, Conditional. In the graph topology these are how participants are arranged.
- **Action constructs** are where work happens: function calls, human-interaction gates, containerized agents, in-process model calls.

A process is a composition of constructs; a control-flow construct contains other constructs, action constructs are the leaves that do work.

### Run

A run is one execution of a process, triggered by an API call, an application, or the CLI. Many runs execute concurrently — of the same process or different ones — and each run is bound to exactly one process. The run is the live instance; the process is the definition it enacts.

## Participant and Role: the meaning of action constructs

Participant and Role are the conceptual lens on action constructs — they describe *who acts* and *under what contract*.

### Participant

A participant is the entity that acts at an action construct — what the construct delegates work to.

**Entity types that can be participants:**

- Autonomous AI agents (an agent in a container)
- LLM-backed reasoning steps (in-process model calls)
- Humans (approval gates, reviews, decisions)
- Tools (API calls, scripts, functions)
- External services (CI pipelines, deployment systems, databases)
- Communication channels (Slack, email, webhooks)
- ML models (classifiers, embeddings, predictions)

These differ in implementation, not in their relationship to the process: each appears as an action construct fulfilling a role.

### Role

A role is a pure contract — what must be done, not how or by whom.

A role specifies:

- **Purpose**: what the role exists to accomplish
- **Scope**: what it is allowed to touch (files, services, resources)
- **Input / output schema**: the data it requires and must produce
- **Permissions**: what it is authorized to do
- **Quality controls**: timeout, retries, and success criteria

**Example**: a `test_writer` role — "Given a feature spec and public interfaces, produce test files in `tests/`. No access to implementation source. Must produce test evidence." A participant (an agent in a specific image, a particular model) fulfills that role inside an action construct.

## Design Principles

1. **A system offers; a process defines; a run enacts.** These are three levels — the deployment catalog, the runnable definition, and the live instance — and they never collapse into one another.

2. **Processes are topology-agnostic.** A graph is today's topology, not the model's commitment. The process's identity and contract are independent of how its constructs coordinate.

3. **Processes are lifespan-agnostic.** Bounded jobs and indefinite standing behaviors are equally processes. The model assumes no terminal goal.

4. **Action constructs are participants performing roles.** The participant is the entity; the role is the contract; the action construct is how they appear in a process. Control-flow constructs express topology, not work.

5. **Enforcement at the boundary.** The platform validates input and output at each construct's boundary against its declared contract. The construct's implementation does not perform this validation — the platform enforces it.

6. **The execution engine is an implementation detail.** How a process actually runs is hidden. The ontology — system, process, topology, construct, run — is the stable vocabulary; the engine beneath it can change without changing the model.
