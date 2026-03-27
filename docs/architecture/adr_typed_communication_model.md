# ADR: Typed Communication Model and Node Contracts

## Status

Draft

## Guiding Principles

**Declare structure, implement behavior.**

The system specification is declarative -- topology, contracts, state schemas, and constraints are expressed in data (JSON/YAML), not code. Handler logic, error recovery, and decision-making are implemented in code. Agent Foundry does not attempt to be a general-purpose DSL.

**Experimentation is a core capability.**

Agent Foundry must support running the same system structure with different implementations -- swapping LLM providers, models, or human reviewers into the same topology without changing the system specification. This requires a clean separation between the node contract (what data flows) and the role implementation (how work gets done).

**No silent failures.**

Contract violations -- a handler writing an undeclared key, a node producing output that doesn't match the state schema, a type mismatch -- must fail loudly and immediately. Silent drops, swallowed errors, and best-effort behavior hide bugs that compound in autonomous systems.

## Context

Agent Foundry compiles `GraphWiringPlan` definitions into executable LangGraph graphs. Today, all graphs -- top-level and subgraph -- are compiled with `StateGraph(dict)`, meaning shared state is an untyped dictionary. Any node can write any key, and there is no enforcement that nodes respect the intended state schema.

Without typed state enforcement, nodes can and do inject undeclared keys (e.g., `_loop_exhausted` from the iteration limiter), and nothing prevents schema drift over time. Agentic systems require strict typing of shared state to be stable and predictable -- silent data corruption or undeclared state mutations undermine the reliability that autonomous operation demands.

Additionally, the responsibilities of `NodeDef`, `RoleSpec`, and handlers are not cleanly separated. Implementation details like `role_instructions_path` and `prompt_preamble` currently live in node config, and the data contract (inputs/outputs schema) currently lives on the role spec. This conflation prevents clean implementation swapping, undermining experimentation as a core capability.

## Decisions

### 1. Every `GraphWiringPlan` must declare a strongly-typed communication model

Today the communication model consists of a `state_schema` -- an inline JSON Schema declaring the shared state structure. As Agent Foundry evolves, the communication model will expand to include event schemas and message channel schemas, each enforced with the same compile-time and runtime validation.

The `state_schema` is required on every `GraphWiringPlan` -- top-level and subgraph. This keeps the system specification fully declarative and language-agnostic.

At compile time, `compile_plan` uses the `state_schema` to create a typed `StateGraph` instead of `StateGraph(dict)`. LangGraph creates one channel per declared field. At runtime, if a handler returns a key not in the `state_schema`, execution fails immediately with an error. No silent failures.

```json
{
  "goal": "data-processing-pipeline",
  "state_schema": {
    "type": "object",
    "properties": {
      "input_data": { "type": "object" },
      "result": { "type": ["object", "null"] },
      "status": { "type": ["string", "null"] },
      "passed": { "type": ["boolean", "null"] }
    },
    "required": ["input_data"],
    "additionalProperties": false
  },
  "nodes": [...]
}
```

### 2. Nodes own the data contract

Each node declares its input and output schemas as JSON Schema in the system specification.

At compile time, the compiler validates that every node's declared outputs are a subset of the `state_schema` fields. This is static verification -- no data needs to flow.

### 3. Role specs own the implementation

A role spec binds a role name to a concrete implementation. It carries:

- **`implementation`**: module, class, and method pointer
- **`quality_controls`**: timeout, retries (implementation-scoped)
- **`tags`**: metadata for discovery and experimentation
- **Implementation-specific config**: e.g., `role_instructions_path`, `prompt_preamble` for LLM container implementations

A role spec does not declare data contracts. The node's contract is the invariant; the role spec is the swappable part.

### 4. Role specs are swappable for experimentation

The same system specification (same topology, same node contracts, same state schemas) can be run with different role spec bindings. This enables experimentation: run the same feature implementation with Claude, Codex, or a human reviewer by swapping role specs at compile time.

The experiment surface is the mapping of role names to role spec identifiers. Everything else -- system topology, node contracts, state schemas -- stays fixed. The compiler re-validates each configuration.

### 5. `_loop_exhausted` must move out of shared state

The iteration limiter currently signals loop exhaustion by injecting `_loop_exhausted: true` into the shared state dict. With typed state schemas, this is a compiler concern leaking into application-level state.

This signal must move to a framework-internal mechanism (e.g., LangGraph `Command` objects, a separate control channel, or handler return metadata) that does not pollute the declared state schema.

### 6. Compile-time validation

At compile time, the compiler validates every node's declared inputs and outputs against all declared communication schemas. Today this means the `state_schema`; when event buses and message channels are added, the same validation extends to those schemas.

Current checks:

- Every `GraphWiringPlan` has a `state_schema`
- Every node's declared output keys are a subset of the `state_schema` properties
- Every node's declared input keys exist in the `state_schema` properties
- The `state_mapping` keys (for subgraph nodes) align with both the parent and subgraph schemas

## Future Considerations

### Extending the communication model: event buses and message channels

The communication model will expand beyond shared state. Event buses and message channels are planned extensions, each with their own declared schemas. A node participating in multiple communication paths will declare contracts for each.

These will be additive, peer fields alongside `state_schema`:

```json
{
  "state_schema": { ... },
  "event_schemas": { "review_complete": { ... }, "test_failed": { ... } },
  "channel_schemas": { "feedback": { ... } }
}
```

The current design does not need to anticipate the exact shape of these schemas. The guiding principles (declarative contracts, no silent failures) and the compile-time validation framework carry forward directly.

### Agent orchestrators

Agent Foundry will support agent orchestrators where an agent decides which nodes execute next (no static edges). Dynamic routing does not weaken schema enforcement -- the communication model remains the invariant regardless of how a node is invoked. This is the strongest argument for typed communication: with dynamic orchestration, the communication model is the only contract that can be statically verified.

### Tags for role discovery

Role spec tags (`tags` field) are preserved for future use in experiment configuration and dynamic role discovery (e.g., "find all roles tagged `reviewer`").

### Abstract workspace constraints

Node config currently expresses filesystem access constraints as concrete paths (e.g., `acp_readonly_dirs: ["/workspace/src"]`). These should evolve to express intent ("must not modify production code") at the node level, with the role spec translating intent into mechanism for the specific implementation. This change is deferred.

## Consequences

- All existing `GraphWiringPlan` definitions must add a `state_schema`
- Node definitions in system specs must add `inputs_schema` and `outputs_schema`
- Role specs must absorb implementation-specific config currently in node config
- The `inputs_schema` and `outputs_schema` fields on `RoleSpec` become unnecessary (contract moved to node) and should be removed or deprecated
- The iteration limiter in the compiler must be reworked to avoid writing to shared state
- Compile time increases slightly due to schema validation, but catches errors that would otherwise surface as silent data loss at runtime
