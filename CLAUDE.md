This project uses **Jig** for development workflow management.
See `jig.config.md` for pipeline configuration.

# Agent Foundry

A platform for building agentic workflow systems. Agent Foundry provides composable, typed primitives that compile to executable LangGraph graphs. Users define workflows as primitive trees; the platform handles compilation, execution, and state management.

## Foundational Motivation

**Decision rule:** when a design choice makes things easier for products (composing, extending, experimenting) but harder inside the platform (more indirection, more dispatch logic, more runtime work), favor the product. Push complexity into the platform, not onto products.

Agent Foundry exists for two intertwined reasons:

**To accelerate development of high-quality agentic systems.** Agentic systems share a large body of infrastructure — container lifecycle, protocol handling, structured output, lockdown, compilation, state flow, recovery. Products should not rebuild this. Agent Foundry centralizes the mechanics. Building a new agentic system means composing primitives and declaring agent behavior, not reimplementing infrastructure. Centralize hardening, testing, and security fixes. Any improvement in one place benefits every product built on the platform.

**To make experimenting with agentic system design fast.** LLMs and systems of agents are new; the best designs aren't known yet, and they will be discovered by iterating through experiments. Every capability Agent Foundry offers is shaped by this goal: shorten the cycle between "I want to try a change" and "I can see the outcome."

Concretely, this means:

- **Rich primitive and execution-strategy menu.** The platform ships a broad set of control-flow primitives, action primitives, and execution strategies (container, SDK, API). Products compose and recombine these rather than building execution infrastructure.
- **Easy agent-behavior swaps.** The things products want to change most often — prompts, instructions, schema descriptions, response channels, executors — are callable fields on the primitive. Swapping any of them is a one-line change in a product declaration. No framework code is modified to try a different prompt.
- **Open to application extension.** Products can define their own `Primitive` subclasses, register their own compilers and validators, and introduce their own executors. The platform is extensible through registries and field callables, not by editing its core.
- **Support for tracking change outcomes.** The primitive is a data structure — a declaration. Future capabilities (naming/versioning agent configurations, associating parameters and instructions with a version, attaching outcome grades to a run) build on this: the declaration is the unit being versioned and graded.

## Platform Principles

**Agent Foundry is a platform, not a library.** Users (like Archipelago) build custom primitive types, action variants, and agent implementations on top of it. Design every API surface for extension.

**Agent Foundry is a declarative platform.** The product's primitive declaration is the *complete, authoritative specification* of an agent (or any primitive) — prompt logic, instructions, response channel, execution strategy, access rights, reuse policy. Reading a product's declaration tells you what the primitive does and how it runs. The platform is machinery that executes what's declared; it does not make product decisions through defaults. Any behavior-defining choice that matters to the product must live on the primitive, not in platform code. When the platform offers multiple ways to do a thing (e.g., container vs. SDK vs. API execution), every way is a library capability the product picks from — none is "the default."

**Agent Foundry is safe by default.** For any field where absence of configuration could mean "more access" or "less access," absence means "less access." Filesystem visibility, writability, permissions, and similar controls default to deny; the product explicitly opts in to each grant. For fields where the choice carries semantic weight (e.g., response channel, executor), there is no default — the product must choose. Misconfiguration produces loud, localized failures ("permission denied writing to /workspace/src"), never silent grants of authority or implicit behavior.

**Strict typing at all boundaries.** Public APIs accept and return Pydantic models, never raw dicts. LangGraph's dict-based internals are encapsulated within the compiler. State flows between primitives as typed models — no string-keyed dictionaries, no hard-coded keys, no untyped smuggling of internal bookkeeping through state.

**Extensibility via registries.** The compiler dispatches to per-type compiler functions via a registry, not `isinstance` chains. The validator does the same. New primitive types register their own compiler and validator without modifying core code. Unknown types raise loudly — silent fallback is rejected. Same pattern applies to future extension points (action executors, interaction handlers).

**Composition over inheritance for state models.** State models use Pydantic BaseModel with composition. No subclass hierarchies between state types. Type boundaries use exact identity checks (`is`), not subtype checks (`issubclass`).

**Primitives are a tree, not a graph.** Composition is by direct object reference. No string-based names or IDs for cross-referencing. Scope is local — a primitive's children are self-contained subtrees. This guarantees that validation is local and compilation is recursive.

**Accumulated state, not pipeline.** Composite primitives (Sequence, Loop, Retry, Conditional) maintain accumulated state within their subgraph. Each step reads its declared input fields from the accumulated state and merges its output fields back. State grows — it never shrinks within a subgraph. The composite's output type selects which fields leave the subgraph scope. This enables function reusability: a step only declares the fields it needs, not the full composite input.

## Primitive Taxonomy

**Control flow primitives** structure the graph:
- **Sequence** — linear execution of steps
- **Loop** — iterate over a collection
- **Retry** — repeat until condition met or attempts exhausted
- **Conditional** — branch based on state

**Action primitives** do work at the leaves:
- **FunctionAction** — synchronous in-process function call
- **GateAction** — block for human interaction, return response as typed output
- Future: ServiceAction (API calls), AgentAction (containerized agents), etc.

Control flow primitives compose other primitives (including other control flow). Action primitives are leaves — they transform typed input to typed output.

## Archipelago

An autonomous software development system built on Agent Foundry. Uses a system of AI agents to perform software engineering tasks.

## Development Practices

- **Test-Driven Development (TDD)**: Write tests before implementation. Red-green-refactor cycle. All code changes must be covered by tests.
- **Trunk-Based Development**: Work directly on `main` with short-lived branches. Keep commits small and atomic. No long-lived feature branches.

## Tech Stack

- **Python 3.14**
- **LangGraph**: Orchestration layer for agentic workflows
- **LangChain**: Component library (models, tools, retrieval, structured outputs, integrations)
- **Pydantic**: Data validation and settings management
- **Pytest**: Testing framework
- **PDM**: Package manager

## Project Structure

- `pyproject.toml`: Project configuration and dependencies (PDM)
- `src/agent_foundry/`: Source code
- `tests/agent_foundry/`: Tests

## Commands

- `pdm add <package>`: Add a dependency
- `pdm format`: Find and fix format violations`
- `pdm lint`: Run the linter
- `pdm test-all`: Run all tests
- `pdm test-integration`: Run integration tests
- `pdm test-unit`: Run unit tests
- `pdm typecheck`: Run Pyright typechecking

## Data Model Conventions

When designing or modifying Pydantic models, follow these rules:

- **Enumerated values** → `StrEnum` if code branches on the value;
  free `str` with suggested taxonomy in the field description if the
  value is only displayed or logged. Decision rule: "Does any code
  branch on this value?"
- **`Literal` is forbidden** for enumerated values. `StrEnum` members
  are first-class symbols that LSP operations (`findReferences`,
  `goToDefinition`, `rename`, `workspaceSymbol`) can navigate; `Literal`
  string values are not symbols and are invisible to LSP navigation.
  An agent following the LSP-first rule cannot distinguish "genuinely
  unused" from "LSP can't see it" when a routing value is a `Literal`.
  Only allowed fallback: discriminator tags on tagged unions when the
  pinned Pydantic version rejects `StrEnum`-typed discriminator fields —
  in that case write `kind: Literal[SomeEnum.VARIANT] = SomeEnum.VARIANT`.
- **Discriminated unions** use tagged wrapper types with a `kind:
  SomeEnum = SomeEnum.VARIANT` field and
  `Annotated[Union[...], Field(discriminator="kind")]`. Don't rely
  on Pydantic's smart-union field-uniqueness matching.
- **Agent boundaries** use JSON schema injection — role handlers
  inject `Model.model_json_schema()` into the agent prompt; never
  hand-enumerate valid values in role markdown.
- **Every boundary type is a Pydantic `BaseModel`** — runtime
  validation, schema generation, JSON round-trip. Plain dataclasses
  only for internal, non-serialized types.
  