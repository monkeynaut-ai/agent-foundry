# Spec Collaborator Memory

## Project: agent-foundry (demo-archipelago branch)

### Codebase Patterns
- **Module structure**: `src/agent_foundry/<module>/` with `__init__.py`, main logic files, `errors.py`
- **Capability specs**: YAML files in `capabilities/` with fields: name, description, version, implementation (module + class_name), inputs_schema, outputs_schema, tags, quality_controls
- **Handler signature**: `def handler(state: dict[str, Any]) -> dict[str, Any]` -- takes full state dict, returns merged state
- **Handler registry**: Plain `dict[str, Callable]` mapping capability names to handler functions (see `DEMO_HANDLERS` in `demo/runner.py`)
- **Plans**: Static dicts in `planner.py` registered in `_GOAL_PLANS` dict, keyed by goal string
- **Compiler**: `compile_plan(plan, registry, handler_registry=None, enforce_gates=False)` -- uses passthrough if no handler provided
- **Tests**: Class-based grouping, `CAPABILITIES_DIR` fixture pattern, stub handlers for unit tests
- **Validation**: 7-check validator in `validators.py` (duplicates, unknown caps, dangling edges, tool contracts, breakpoints, versions, loop termination)
- **Error classes**: Typed exceptions with structured context fields (see `compiler/errors.py`, `registry/errors.py`)

### Tech Stack
- Python 3.13 (pyproject.toml says 3.13, CLAUDE.md says 3.14 -- actual constraint is pyproject.toml)
- PDM package manager, pytest, Pydantic v2, LangGraph, langchain-anthropic, faiss-cpu, jsonschema
- Feature flags pattern: module-level booleans like `FF_COMPILER`, `FF_TRACING`

### Spec Conventions
- Follow format of `docs/demo-archipelago/archipelago_workflow_orchestrator_feature_spec.md`
- Sections: Objective, Success Criteria, Constraints (Technical/Scope/Quality/Time), Acceptance Criteria (Given/When/Then by phase), PR/Commit Slices, Dependency Graph, Implementation Notes
- PR slices should be vertical (independently mergeable)
- Commits atomic and focused
- TDD: tests before implementation
- Test names: Given/When/Then format
- Each PR lists: files created/modified, acceptance criteria addressed, complexity (S/M/L), dependencies, commit breakdown
- Dependency graph uses ASCII art showing PR relationships

### Key File Paths
- Compiler: `src/agent_foundry/compiler/compiler.py`
- Wiring plan models: `src/agent_foundry/planner/wiring_plan.py`
- Capability spec loader: `src/agent_foundry/registry/spec.py`
- Demo runner (pattern reference): `src/agent_foundry/demo/runner.py`
- Tracer: `src/agent_foundry/observability/tracer.py`
- Existing specs: `capabilities/*.yaml` (12 total: 8 base + 4 archipelago)
- Existing feature spec (format reference): `docs/demo-archipelago/archipelago_workflow_orchestrator_feature_spec.md`
- MVP analysis: `docs/demo-archipelago/archipelago_workflow_orchestrator_mvp_analysis.md`

### Registry Size Notes
- Currently 13 capabilities in `capabilities/` dir (8 framework + 5 archipelago: strategy, architecture, spec, dev_implement, coding_implement)
- Adding new specs changes this count -- must update any tests asserting specific registry size
- Tag searches: "archipelago" currently returns 4 specs (not 5; coding_implement may lack the tag)

### Architectural Separation (spec written 2026-03-02)
- Spec: `docs/agent-foundry-separation-spec.md`
- Key decisions: AF is single package, products own plans (WiringPlanner deleted), registry auto-loads builtins via `importlib.resources`, `with_product_specs()` is the new product entry point
- 5 migration phases: package builtins -> remove WiringPlanner -> separate archipelago package -> lint enforcement -> repo split
- 8 framework specs stay in `agent_foundry/capabilities/`, 5 product specs move to archipelago repo
- Public API surface documented: plan schema, validators, compiler, registry, observability, handler protocol
- Open questions: demo disposition, built-in handler implementations, private PyPI vs git dep, version coordination, test infrastructure sharing

### Adapter Protocol (spec written 2026-03-05)
- Spec: `docs/demo-archipelago/adapter_protocol_spec.md`
- Protocol models go in `src/archipelago/docker_worker/protocol.py`
- Key decisions:
  - Transport-agnostic JSON protocol, first impl is WebSocket
  - Adapter connects outward to Archipelago (not server-in-container)
  - Per-handler ephemeral WebSocket server (not centralized), session ID in URL for future migration
  - Adapter parses interrupt markers + strips ANSI; Archipelago receives only structured messages
  - Container entrypoint runs adapter as PID 1 (remove `sleep infinity` override)
  - Docker exec retained only for utility commands (git, which)
  - `\n` to `\r` conversion encapsulated in adapter (Archipelago sends `\n`, adapter writes `\r`)
- 5 message types: output, interrupt, status (adapter->orch), input, control (orch->adapter)
- 4 PRs: models -> ANSI strip + adapter rewrite -> handler WS client -> entrypoint integration
- Interrupt regexes should move from `interrupts.py` to `protocol.py` so both adapter and detector import from same place
- `SessionManager` stays for recovery.py but handler stops using it
- 426 tests in tests/, 12 in lab/ -- baseline for regression checking
- Container networking: use `host.docker.internal` with `extra_hosts` in create_container()

### Docker Worker Architecture Notes
- `create_container()` currently overrides entrypoint with `sleep infinity` (`container.py:70-72`)
- Handler uses `exec_create`/`exec_start` with `socket=True` to get a PTY stream (`session.py:45-55`)
- Four distinct uses of Docker exec: PTY session (replaced), git clone (stays), image validation (stays), crash recovery git (stays)
- Trust confirmation: retry loop sends `\r` every 2s via PTY, watches output count increase
- Existing adapter in `lab/adapter.py` has three modes: stdin/stdout, Unix socket, WebSocket (all raw bytes)

### Lessons Learned
- Always read existing spec format before writing new specs to match structure exactly
- Read the compiler and wiring plan models to understand integration contracts
- Check for registry size assertions in existing tests when adding new capability specs
- When writing architectural specs, read ALL modules (including errors, imports, execution) to get accurate public API surface
- Current `archipelago/` is already a separate top-level package under `src/` (not nested in `agent_foundry/`), which simplifies separation
- When designing protocols, start with the objective discovery phase to distinguish "what problem are we solving" from "what technology are we using"
- Users often conflate Docker exec (utility commands) with Docker exec (communication channel) -- be precise about which exec calls change
- Trace all usages of a function/class before proposing to replace it (e.g., SessionManager used by handler, InterruptHandler, and recovery.py)
- For protocol specs, document exchange patterns explicitly (fire-and-forget vs request/response) and error handling for each failure mode
