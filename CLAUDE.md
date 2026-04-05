# Agent Foundry

A platform for building agentic workflow systems. Agent Foundry provides composable, typed primitives that compile to executable LangGraph graphs. Users define workflows as primitive trees; the platform handles compilation, execution, and state management.

## Platform Principles

**Agent Foundry is a platform, not a library.** Users (like Archipelago) build custom primitive types, action variants, and agent implementations on top of it. Design every API surface for extension.

**Strict typing at all boundaries.** Public APIs accept and return Pydantic models, never raw dicts. LangGraph's dict-based internals are encapsulated within the compiler. State flows between primitives as typed models — no string-keyed dictionaries, no hard-coded keys, no untyped smuggling of internal bookkeeping through state.

**Extensibility via registries.** The compiler dispatches to per-type compiler functions via a registry, not `isinstance` chains. New primitive types register their own compiler without modifying core code. Same pattern applies to future extension points (action executors, interaction handlers).

**Composition over inheritance for state models.** State models use Pydantic BaseModel with composition. No subclass hierarchies between state types. Type boundaries use exact identity checks (`is`), not subtype checks (`issubclass`).

**Primitives are a tree, not a graph.** Composition is by direct object reference. No string-based names or IDs for cross-referencing. Scope is local — a primitive's children are self-contained subtrees. This guarantees that validation is local and compilation is recursive.

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
- `pdm run pytest`: Run tests
