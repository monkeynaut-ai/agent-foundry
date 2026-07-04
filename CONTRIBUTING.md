# Contributing to Agent Foundry

Thanks for your interest in contributing. This guide covers the design principles the
codebase holds itself to, the conventions for data modeling, and the development workflow.

## Framework principles

Agent Foundry is a typed, boundary-enforced framework for declaring and running
agentic systems. Applications build custom construct types, action variants,
executors, providers, responders, and adapters on top of the framework core.
Design public API surfaces for extension, but keep runtime- and provider-specific
behavior behind explicit seams.

- **Declarative.** An application's construct declaration is the complete,
  authoritative specification of a construct — prompt logic, instructions,
  response channel, execution strategy, access rights, reuse policy, and adapter
  choices. Agent Foundry executes what is declared; it does not make application
  decisions through hidden defaults.
- **Safe by default.** For any field where absence of configuration could mean "more
  access," absence means "less access." Filesystem visibility, writability, and
  permissions default to deny; the application opts in to each grant. Where a
  choice carries semantic weight (response channel, executor, provider, adapter),
  there is no default — the application must choose. Misconfiguration fails loudly
  and locally.
- **Typed boundaries.** Public APIs and construct boundaries use Pydantic models,
  not raw dicts. State flows between constructs through declared input and output
  models. Current engine internals use dictionaries, but that untyped state stays
  encapsulated within the compiler/runtime boundary.
- **Extensibility via registries.** The compiler and validator dispatch to per-type
  functions via a registry, not `isinstance` chains. New construct types register their
  own compiler and validator without modifying core code. Unknown types raise loudly.
- **Adapter seams over lock-in.** Workflow engines, agent harnesses, model
  providers, tools, containers, and observability systems should sit behind
  explicit adapters. Escape hatches are allowed, but should be marked
  non-portable when they bind an application to a specific backend.
- **Composition over inheritance for state models.** No subclass hierarchies between
  state types. Type boundaries use exact identity checks (`is`), not `issubclass`.
- **Constructs are a tree, not a graph.** Composition is by direct object reference — no
  string-based names or IDs for cross-referencing. Validation is local; compilation is
  recursive.
- **Keep experiments comparable.** Agent Foundry should make it cheap to change
  prompts, models, memory strategies, tools, harnesses, and backends while
  preserving a stable typed process frame for comparison and measurement.

## Data model conventions

- **Enumerated values** → `StrEnum` if any code branches on the value; free `str` (with a
  suggested taxonomy in the field description) if the value is only displayed or logged.
- **`Literal` is forbidden** for enumerated values — `StrEnum` members are first-class
  symbols that LSP operations can navigate; `Literal` string values are not. The only
  allowed fallback is a discriminator tag on a tagged union when the pinned Pydantic
  version rejects `StrEnum`-typed discriminator fields.
- **Discriminated unions** use tagged wrapper types with a `kind: SomeEnum = SomeEnum.VARIANT`
  field and `Annotated[Union[...], Field(discriminator="kind")]`.
- **Agent boundaries** use JSON-schema injection — inject `Model.model_json_schema()` into
  the prompt; never hand-enumerate valid values in role markdown.
- **Every boundary type is a Pydantic `BaseModel`.** Plain dataclasses only for internal,
  non-serialized types.

## Development practices

- **Test-Driven Development.** Write tests before implementation; red-green-refactor. All
  code changes must be covered by tests.
- **Trunk-Based Development.** Work on `main` with short-lived branches. Keep commits small
  and atomic; no long-lived feature branches.

## Tech stack

Python 3.14 · LangGraph · Pydantic · Pytest · [PDM](https://pdm-project.org/).

## Commands

| Command | Purpose |
|---------|---------|
| `pdm add <package>` | Add a dependency |
| `pdm format` | Find and fix format violations |
| `pdm lint` | Run the linter |
| `pdm typecheck` | Run Pyright typechecking |
| `pdm test-unit` | Run unit tests |
| `pdm test-integration` | Run integration tests |
| `pdm test-all` | Run all tests |

## Further reading

- Architecture and decision records: [`docs/architecture/`](docs/architecture/)
- Documentation map and cleanup status: [`docs/README.md`](docs/README.md)
