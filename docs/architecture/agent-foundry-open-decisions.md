# Agent Foundry: Open Architecture Decisions

A concise checklist of what we still need to **decide and document**. This is a
reminder index only — the context, current state, and open questions behind each
item live in [agent-foundry-architecture.md](agent-foundry-architecture.md).

**Framing:** the bottom of the stack (Construct, compiler, validator, Run) is
mature and matches our principles. The top (System, Topology, Role, lifespan,
triggers, versioning) is ontology without code. These decisions are about the
top, plus a few guardrails missing from the mature bottom.

## Unrealized concepts (top of stack)

- [ ] **System** — the deployment/catalog layer. *(OQ-SYS-1..3)*
  - Catalog & identity of processes; versioning ownership.
  - Typed seam for System-owned shared resources (knowledge stores, auth).
  - How a Run selects a process and what System contributes to `RunContext`.
- [ ] **Topology** — make graph a choice, not a commitment. *(OQ-TOP-1..3)*
  - Where the topology seam lives.
  - The topology-agnostic process contract (entry/IO/state) all must honor.
  - Engine boundary: per-topology engine vs. shared, what stays hidden.
- [ ] **Role** — first-class participant contract. *(OQ-ROLE-1..3)*
  - Extract Role from the implicit bundle of `AgentAction` fields.
  - Portability of one role across participant kinds.
  - Whether scope/permissions move from participant to role.
- [ ] **Process lifespan** — support unbounded/standing processes. *(OQ-LIFE-1..2)*
  - Representation (topology vs. flag vs. outer driver).
  - State that persists across cycles (couples to durability).
- [ ] **Participant breadth** — services, channels, ML models. *(OQ-PART-1)*
  - New action constructs vs. new executors vs. roles on generic participants.

## Capabilities the declarative model promises but lacks

- [ ] **Run durability & recovery** — survive restart; resume gated/standing runs. *(OQ-DUR-1..2)*
- [ ] **Trigger / entry model** — how API/app/CLI start a run. *(OQ-TRIG-1..2)*
- [ ] **Process versioning & outcome grading** — version the declaration, grade the run. *(OQ-VER-1..2)*

## Guardrails missing from the mature bottom

- [ ] **Typed internal state** — eliminate `Retry`'s string-channel smuggling or formally constrain concurrency. *(OQ-ENF-1)*
- [ ] **Concurrency invariant** — enforce or remove the "execution is sequential" assumption. *(OQ-ENF-2)*
- [ ] **Construct-name uniqueness** — enforce at validation or remove the dependence. *(OQ-ENF-3)*

## Boundary / surface

- [ ] **Public API facade** — define the curated surface vs. internals (`__init__.py` is empty today). *(OQ-API-1)*

## Dependencies & sequencing

Several decisions are coupled and can't be made independently. Decide the
upstream item first; it constrains the dependents.

- **System identity (OQ-SYS-1)** is upstream of:
  - **Versioning (OQ-VER-1)** — what identifies a version depends on whether the
    System catalog is the registry of record.
  - **Trigger/catalog binding (OQ-TRIG-2)** — how a trigger names a process
    depends on how the catalog identifies processes.
  - **Run selection (OQ-SYS-3)** — selecting a process presupposes the catalog.
- **Role (OQ-ROLE-1)** is upstream of:
  - **Participant breadth (OQ-PART-1)** — whether new participant kinds arrive as
    constructs, executors, or role bindings depends on whether Role exists.
  - **Scope/permissions placement (OQ-ROLE-3)** — only meaningful once Role is a
    type.
- **Process lifespan (OQ-LIFE-1)** is coupled with **Run durability (OQ-DUR-1)** —
  standing processes require persisted cross-cycle state; decide them together.
- **Topology seam (OQ-TOP-1)** is upstream of **lifespan representation
  (OQ-LIFE-1)** if unbounded processes are modeled as a topology rather than a
  flag or outer driver.

Suggested ordering: **System → Topology → Role**, then the capabilities
(durability+lifespan together, then triggers, then versioning) that depend on
them. The enforcement guardrails (OQ-ENF-*) and the public API facade (OQ-API-1)
are independent and can proceed in parallel at any time.

## Repo hygiene (not architecture, but resolve before publishing)

- [ ] `observability/` empty dir shadowing `telemetry/` — resolve or remove.
- [ ] `agents/docker_v2/` orphaned experiment — promote behind existing seams or remove.
