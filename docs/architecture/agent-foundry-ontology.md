# Agent Foundry Ontology: System, Participant, Role

Agent Foundry builds **systems**. A system is an orchestration of **participants**, each performing a **role**. These three concepts -- system, participant, role -- form the platform's conceptual model. Everything else (graphs, nodes, edges, containers) is execution-layer machinery that implements this model. The ontology is independent of any execution engine; LangGraph is the current engine, but the model is designed to survive a change.

## Core Concepts

### System

A system orchestrates **participants**, not roles. Roles are contracts sitting in a registry -- they don't do anything on their own. Participants are the entities that actually exist and act. A system declares which participants are involved and how they interact.

A system declares:
- **Participants**: which entities are involved, what roles they perform, how they're implemented
- **Interactions**: how participants communicate and in what order
- **Entry point**: where execution begins
- **Breakpoints**: where execution pauses for external input
- **Version pins**: which role versions this system expects

A system is the unit of deployment. Archipelago is a system. A future knowledge-management pipeline is a system. Each is built on Agent Foundry's infrastructure but defines its own participants, roles, and interactions. Roles are referenced indirectly -- through the participants that fulfill them.

### Participant

A participant is an entity in a system that fulfills a role using a specific implementation.

A participant declares:
- **Identity**: a unique id within the system
- **Role reference**: which role this participant fulfills (by name and version)
- **Configuration**: context-specific overrides (which repo, which model, environment variables)

**Example**: The `test_writer` participant in Archipelago fulfills the `test_writer` role using the `archipelago-test-writer` Docker image with Claude Code.

**Entity types that can be participants:**
- Autonomous AI agents (Claude Code in a container)
- LLM-backed reasoning steps (in-process model calls)
- Humans (approval gates, reviews, decisions)
- Tools (API calls, scripts, functions)
- External services (CI pipelines, deployment systems, databases)
- Communication channels (Slack, email, webhooks)
- ML models (classifiers, embeddings, predictions)

All of these are participants. They differ in implementation, not in their relationship to the system.

### Role

A role is a pure contract. It defines what needs to be done, not how or by whom.

A role specifies:
- **Purpose**: what the role exists to accomplish
- **Scope**: what the role is allowed to touch (files, services, resources)
- **Input schema**: what data the role requires
- **Output schema**: what data the role must produce
- **Permissions**: what the role is authorized to do
- **Implementation**: how this role is fulfilled (module + class, Docker image, external service endpoint)
- **Quality controls**: timeout, retries, and success criteria

**Example**: The `test_writer` role defines: "Given a feature spec and public interfaces, produce test files in `tests/`. No access to implementation source. Must produce test evidence."

## Mapping to the Execution Layer

The ontology maps to the current LangGraph-based execution layer as follows:

| Ontology concept | Current code artifact | Current class/file |
|-----------------|----------------------|-------------------|
| System | Graph wiring plan | `GraphWiringPlan` in `planner/wiring_plan.py` |
| Compiled system | LangGraph StateGraph | Output of `compile_plan()` in `compiler/compiler.py` |
| Participant | Node definition + handler binding | `NodeDef` in `planner/wiring_plan.py` |
| Role | Capability spec (YAML/JSON) | `CapabilitySpec` in `registry/spec.py` |
| Role registry | Capability registry | `CapabilityRegistry` in `registry/registry.py` |

The "Current" column reflects the codebase as of this writing. A rename from "capability" to "role" is planned (see work-status.md #30).

## Design Principles

1. **Systems compose participants, not roles.** A system doesn't just list roles -- it specifies who fills each role and how they interact. Two systems can use the same roles with different participants.

2. **Roles are complete definitions.** A role spec defines the contract (schemas, permissions, scope) and the implementation (how the role is fulfilled). Different roles with different implementations are different roles -- there is no need for an indirection layer between contract and implementation.

3. **Participants bind roles to context.** A participant references a role and provides context-specific configuration (which repo, which model, environment overrides). The role defines what to do and how; the participant defines where and with what settings.

4. **The execution layer is an implementation detail.** LangGraph is how we orchestrate today. The ontology does not depend on it. "Node" and "edge" are LangGraph concepts. "Participant" and "interaction" are system concepts.

5. **Enforcement at the boundary.** The framework validates inputs and outputs at the participant boundary against the role's schemas. Neither the role nor the implementation needs to know about validation -- the framework enforces the contract.

## Vocabulary Migration

| Old term | New term (ontology) | New term (code, planned) |
|----------|-------------------|------------------------|
| graph / wiring plan | System | `SystemDef` (future, see #32) |
| node (conceptual) | Participant | `ParticipantDef` (future, see #32) |
| node (LangGraph) | node (unchanged) | LangGraph `StateGraph` node |
| capability | Role | `RoleSpec` |
| capability spec | Role spec | `RoleSpec` (YAML/JSON file) |
| capability registry | Role registry | `RoleRegistry` |
| CapabilityStack (ACP) | Role stack | `RoleStack` |
| capability_versions | role_versions | `GraphWiringPlan.role_versions` |
| NodeDef.capability | participant's role reference | `NodeDef.role` |
