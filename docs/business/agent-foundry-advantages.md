# Agent Foundry: Competitive Advantages

This is a living document. It catalogs the architectural and operational advantages that Agent Foundry provides over standard LangGraph application development. Each advantage is grounded in a specific design decision and its observable consequences.

## Declarative role specifications

LangGraph treats nodes as plain Python functions with no formal contract. A node's inputs, outputs, and behavior are implicit in its code.

Agent Foundry adds a declarative specification layer: each role is defined in a versioned YAML file with explicit input/output JSON schemas and quality controls. A role registry loads and indexes these specs at startup. The implementation is declared separately at the participant level, not in the role spec -- allowing the same role to be fulfilled by different implementations across systems.

**What this enables:**

- **Cross-system reuse.** A role defined once can be referenced by participants in multiple systems. Archipelago's `human_approval_gate` role and a future knowledge-management system can share the same contract without duplication.
- **Governance and auditability.** Every role has a version and a schema contract. This makes it possible to answer "what changed between v1.0.0 and v1.1.0 of this role?" and to enforce review processes on role definitions independent of the systems that use them.
- **Implementation flexibility.** Because the role is a pure contract (no implementation pointer), the same role can be fulfilled by a containerized Claude Code agent, an in-process LLM call, a human reviewer, or a third-party service. The choice of implementation belongs to the participant, not the role.
- **Tooling potential.** Machine-readable specs enable automated validation, visualization, catalog UIs, and compatibility checks that are not possible when roles exist only as function signatures in code.

## Declarative system definitions

LangGraph expects developers to construct graphs imperatively: call `graph.add_node()`, `graph.add_edge()`, and `graph.compile()` in Python code.

Agent Foundry defines systems as data. A system definition file (JSON) declares participants, their roles, interactions, entry points, breakpoints, and role version pins. A compiler reads this file, resolves roles from the registry, binds implementations, and produces a runnable graph.

**What this enables:**

- **Separation of topology from logic.** The shape of the system (which participants exist, how they interact) is independent of the code that implements each role. Changing the interaction order or adding a new participant does not require modifying handler code.
- **Non-developer accessibility.** A JSON file describing a system is readable and editable by people who are not Python developers -- product managers, system designers, operations teams.
- **Dynamic system construction.** Because the system is data, it can be generated programmatically. A planner agent could produce a system definition file, and the compiler would build and execute it without any imperative graph-building code.
- **Validation before execution.** The compiler can check that all referenced roles exist in the registry, that versions match, and that interaction targets are valid -- before any participant runs.

## Container-backed execution

LangGraph nodes execute as in-process function calls. They share the host process's memory, filesystem, and permissions.

Agent Foundry's Agent Container Protocol (ACP) allows participants to delegate execution to isolated Docker containers. Each container runs its own AI agent (e.g., Claude Code) with defined resource limits, network policies, and a bidirectional WebSocket protocol for communication with the orchestrator.

**What this enables:**

- **True agent autonomy.** A containerized agent can clone repositories, install dependencies, write code, run tests, and iterate -- all within a sandboxed environment. This is not possible with in-process function calls.
- **Resource isolation.** Memory limits, CPU quotas, PID limits, and filesystem restrictions are enforced per container. A runaway agent cannot starve other participants or crash the orchestrator.
- **Security boundaries.** Containers run with dropped capabilities, read-only root filesystems, and environment variable allowlists. The blast radius of a compromised or misbehaving agent is contained.
- **Multi-turn sessions.** ACP supports session persistence across turns (`--resume SESSION_ID`). An orchestrator can pause an agent, run a gate check with a different participant, and resume the same agent session with feedback -- preserving full conversation context.
- **Heterogeneous agents.** Different containers can run different agent implementations (Claude Code, Codex, custom Python agents, future toolchains) behind the same protocol. The orchestrator doesn't need to know what runs inside the container.
