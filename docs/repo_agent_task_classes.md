# Repo-Agent Responsibilities and Task Interfaces

Modern software product engineering systems increasingly combine **humans and specialized agents** to perform different kinds of work. Product managers, designers, and engineers define goals, constraints, and architectural direction, while automated agents execute bounded technical tasks inside controlled environments. A containerized coding agent sits at the layer where abstract engineering intent becomes concrete repository operations: reading code, running tools, generating patches, executing tests, and producing reports.

Within a larger engineering workflow, the repo-agent is responsible specifically for **repository work**: inspecting a version-controlled codebase, proposing or applying changes, validating those changes, and producing evidence about repository state. Humans or higher‑level orchestration systems decide *what work should happen* and *under what constraints*. The repo-agent container is responsible for *how repository operations are executed safely and predictably* within those constraints.

This document therefore defines **the responsibilities and integration interfaces of a containerized repo-agent**. Rather than being primarily a taxonomy of task types, it specifies the contracts that describe work the agent can perform. Each responsibility domain below defines a standardized task interface describing required inputs, allowed operations, invariants, validation requirements, and expected outputs.

The taxonomy of task classes exists only to standardize these interfaces so that orchestration systems and humans can reliably integrate the repo-agent into larger software engineering workflows.

---

## Table of Contents

- [Repo-Agent Responsibility Model](#repo-agent-responsibility-model)
- [Repo-Agent Task Interface](#repo-agent-task-interface)
- [Execution Scope Model](#execution-scope-model)
- [Uncertainty Modes](#uncertainty-modes)
- [Task Interfaces by Responsibility Domain](#task-interfaces-by-responsibility-domain)
  - [1. Diagnostic / Root-Cause Task Interface](#1-diagnostic-root-cause-task-interface)
  - [2. Review / Verification Task Interface](#2-review-verification-task-interface)
  - [3. Feature Implementation Task Interface](#3-feature-implementation-task-interface)
  - [4. Corrective / Bug-Fix Task Interface](#4-corrective-bug-fix-task-interface)
  - [5. Refactor / Structural Transformation Task Interface](#5-refactor-structural-transformation-task-interface)
  - [6. Optimization / Non-Functional Improvement Task Interface](#6-optimization-non-functional-improvement-task-interface)
  - [7. Test / Verification Asset Task Interface](#7-test-verification-asset-task-interface)
  - [8. Observability / Instrumentation Task Interface](#8-observability-instrumentation-task-interface)
  - [9. Tooling / Developer Experience Task Interface](#9-tooling-developer-experience-task-interface)
  - [10. Dependency / Build / Infrastructure Task Interface](#10-dependency-build-infrastructure-task-interface)
  - [11. Documentation / Knowledge Artifact Task Interface](#11-documentation-knowledge-artifact-task-interface)
  - [12. Migration / Large-Scale Transformation Task Interface](#12-migration-large-scale-transformation-task-interface)
  - [13. Policy / Compliance Task Interface](#13-policy-compliance-task-interface)
  - [14. Proposal / Patch-Synthesis Task Interface](#14-proposal-patch-synthesis-task-interface)
- [Cross-Cutting Execution Controls](#cross-cutting-execution-controls)
- [Compact Router View](#compact-router-view)
- [Notes on Use](#notes-on-use)
- [Node Execution (Container) Profile](#node-execution-container-profile)

---


<a id="repo-agent-responsibility-model"></a>
# Repo-Agent Responsibility Model

The repo-agent container is responsible for executing repository work in several broad domains:

- **Investigation** — analyzing repository state to explain failures or anomalies
- **Evaluation** — validating existing code changes or claims about repository behavior
- **Code Mutation** — modifying repository artifacts to implement, fix, or restructure behavior
- **System Improvement** — improving non-functional qualities such as performance, observability, or developer experience
- **Infrastructure Maintenance** — maintaining dependencies, build systems, and repository infrastructure
- **Governance and Compliance** — enforcing organizational policies and security constraints
- **Knowledge Artifact Maintenance** — maintaining documentation and repo-resident knowledge
- **Change Proposal Generation** — producing patches or implementation plans without applying them

Each responsibility domain is implemented through **task interfaces** that define how orchestration systems request work from the repo-agent.

---

# Repo-Agent Task Interface

All repo-agent work is expressed through a standardized task interface describing the operational contract between the orchestrator and the container. The interface specifies **what work the agent performs**, while additional execution controls (defined later in this document) specify **how the agent is allowed to execute that work** within the broader engineering workflow.

```text
Task = (
  Intent,
  Inputs,
  Execution Scope,
  Constraints,
  Validation,
  Outputs,
  Success Criteria,
  Uncertainty Mode

  + Execution Controls
)
```

Execution controls are cross-cutting parameters applied to the task contract that constrain mutation authority, validation requirements, and acceptable operational risk. These controls allow the same task interface to be executed under different operational regimes (for example investigation, automated remediation, or human‑review workflows).

## Interface Fields

**Intent**\
The high-level purpose of the task.

**Inputs**\
Artifacts that describe the problem or request (bug reports, specifications, diffs, benchmarks, etc.).

**Execution Scope**\
Defines both **where** the agent may operate in the repository and **what operations** it may perform there. This combines the concepts of *scope* (files, modules, or repo regions the agent may access) and *permissions* (allowed mutations such as read, edit, add files, run commands, etc.).

**Constraints**\
Conditions that bound task execution or outcomes. These may include **invariants** (properties that must remain true after execution, such as behavior preservation or API stability) and **operational limits** (such as runtime, file changes, or search breadth). Future versions of the interface may also incorporate additional constraint categories such as compatibility constraints, policy constraints, environment constraints, and coordination constraints.

**Validation**\
Procedures required to verify correctness of the task outcome.

**Outputs**\
Artifacts produced by the task.

**Success Criteria**\
Conditions under which the task is considered complete.

**Uncertainty Mode**\
The expected degree of discovery required during execution.

**Execution Controls**\
Additional parameters that constrain *how* the agent executes the task (for example mutation authority, validation depth, and acceptable risk). These controls apply across many task classes and are defined in detail in the section **Cross-Cutting Execution Controls**.

---

# Execution Scope Model

Permissions are defined along two axes.

### Scope

- Exact files
- Directory / module subtree
- Dependency radius from seed files
- Whole repo
- Fixed scope vs expandable-with-justification

### Permissions

- Read
- Edit
- Add
- Delete
- Rename / move
- Modify tests
- Modify docs
- Modify configs
- Modify CI / build
- Modify dependencies / lockfiles
- Execute commands
- Produce patch only vs apply patch

---

# Uncertainty Modes

- **Closed-form** — the transformation is well specified
- **Diagnostic** — root cause must be discovered
- **Exploratory** — search across possible improvements
- **Generative** — synthesize design and implementation
- **Verification-led** — validate a claim or change

---

# Task Interfaces by Responsibility Domain

Each of the following sections defines a **specialized task interface** implementing one of the repo-agent responsibility domains.

---

# 1. Diagnostic / Root-Cause Task Interface {#diagnostic-root-cause}

**Purpose**\
Identify the root cause of a failure, regression, or anomalous behavior in the repository.

### Required Inputs

- Failure description or bug report
- Reproduction artifact (failing test, logs, trace, etc.)
- Initial execution scope

### Execution Scope (Default)

**Scope**: impacted modules or failing tests

**Permissions**

- Read
- Execute commands
- Optional: Add temporary diagnostic tests

### Constraints

**Invariants**

- No production behavior changes
- No dependency changes

**Operational Limits**

- Bounded investigation depth

### Validation

- Reproduce failure
- Gather evidence

### Outputs

- Root cause report
- Minimal reproduction
- Optional fix proposal

### Success Criteria

- Root cause identified with evidence

### Uncertainty Mode

Diagnostic

---

# 2. Review / Verification Task Interface

**Purpose**\
Evaluate a proposed change or repository state against defined requirements.

### Required Inputs

- Diff / pull request
- Review criteria

### Execution Scope

**Scope**: files in diff and impacted dependencies

**Permissions**

- Read
- Execute commands

### Constraints

**Invariants**

- Do not modify repository unless explicitly authorized

### Validation

- Static checks
- Targeted tests

### Outputs

- Review findings
- Approval / rejection recommendation

### Success Criteria

- All material issues identified

### Uncertainty Mode

Verification-led

---

# 3. Feature Implementation Task Interface

**Purpose**\
Implement new user-visible or system-visible behavior from an approved specification.

### Required Inputs

- Feature specification
- Acceptance criteria
- Initial execution scope

### Execution Scope (Default)

**Scope**: target module or service area

**Permissions**

- Read
- Edit
- Add
- Modify tests
- Modify docs

### Constraints

**Invariants**

- Preserve behavior outside feature scope
- Maintain compatibility constraints if specified
- ... what about database schema, (public) api contract, package dependencies ??

**Operational Limits**

- File change limits

### Validation

- Targeted tests
- Lint / typecheck

### Outputs

- Code patch
- Tests
- Implementation summary

### Success Criteria

- Acceptance criteria satisfied

### Uncertainty Mode

Closed-form or Generative

---

# 4. Corrective / Bug-Fix Task Interface

**Purpose**\
Correct unintended behavior while minimizing unrelated changes.

### Required Inputs

- Bug report or failing test

### Execution Scope

**Scope**: implicated modules

**Permissions**

- Read
- Edit
- Modify tests

### Constraints

**Invariants**

- Preserve unrelated behavior
- ... what about database schema, (public) api contract, package dependencies ??

### Validation

- Reproduce failure
- Run impacted tests

### Outputs

- Code fix
- Regression test

### Success Criteria

- Failure no longer reproducible

### Uncertainty Mode

Diagnostic → Closed-form

---

# 5. Refactor / Structural Transformation Task Interface

**Purpose**\
Improve code structure while preserving behavior.

### Required Inputs

- Refactor objective

### Execution Scope

**Scope**: defined module or subsystem

**Permissions**

- Read
- Edit
- Rename
- Modify tests

### Constraints

**Invariants**

- Behavior preserving

### Validation

- Run impacted tests

### Outputs

- Refactored code

### Success Criteria

- Structure improved without behavior change

### Uncertainty Mode

Closed-form or Exploratory

---

# 6. Optimization / Non-Functional Improvement Task Interface

**Purpose**\
Improve measurable non-functional properties such as performance or cost.

### Required Inputs

- Optimization target
- Measurement baseline

### Execution Scope

**Scope**: relevant subsystem

**Permissions**

- Read
- Edit
- Add tests

### Constraints

**Invariants**

- Maintain correctness

### Validation

- Before/after measurement

### Outputs

- Optimized code
- Measurement report

### Success Criteria

- Target metric improvement

### Uncertainty Mode

Exploratory

---

# 7. Test / Verification Asset Task Interface

**Purpose**\
Create or improve automated verification assets.

### Required Inputs

- Test objective or coverage gap

### Execution Scope

**Scope**: tests and related modules

**Permissions**

- Add
- Edit
- Execute commands

### Constraints

**Invariants**

- Do not alter product semantics

### Validation

- Execute tests

### Outputs

- Test assets

### Success Criteria

- Target behavior verifiable

### Uncertainty Mode

Closed-form

---

# 8. Observability / Instrumentation Task Interface

**Purpose**\
Improve diagnosability via logs, metrics, or tracing.

### Required Inputs

- Observability requirement

### Execution Scope

**Scope**: targeted runtime path

**Permissions**

- Edit
- Modify configs

### Constraints

**Invariants**

- Preserve functional behavior

### Validation

- Telemetry verification

### Outputs

- Instrumentation changes

### Success Criteria

- Required telemetry produced

### Uncertainty Mode

Closed-form

---

# 9. Tooling / Developer Experience Task Interface

**Purpose**\
Improve developer workflow and tooling.

### Required Inputs

- DX improvement request

### Execution Scope

**Scope**: tooling or repo configuration

**Permissions**

- Edit
- Add
- Modify configs

### Constraints

**Invariants**

- Preserve supported workflows

### Validation

- Build/test verification

### Outputs

- Tooling improvements

### Success Criteria

- Developer friction reduced

### Uncertainty Mode

Exploratory

---

# 10. Dependency / Build / Infrastructure Task Interface

**Purpose**\
Maintain dependency graph, build system, or runtime configuration.

### Required Inputs

- Dependency or build update request

### Execution Scope

**Scope**: build files, manifests

**Permissions**

- Edit
- Execute commands

### Constraints

**Invariants**

- Repository must remain buildable

### Validation

- Clean build

### Outputs

- Updated configuration

### Success Criteria

- Build succeeds

### Uncertainty Mode

Closed-form

---

# 11. Documentation / Knowledge Artifact Task Interface

**Purpose**\
Maintain documentation and repo knowledge artifacts.

### Required Inputs

- Documentation request

### Execution Scope

**Scope**: docs and examples

**Permissions**

- Edit
- Add

### Constraints

**Invariants**

- Documentation must match repository state

### Validation

- Example checks

### Outputs

- Updated documentation

### Success Criteria

- Documentation gap resolved

### Uncertainty Mode

Closed-form

---

# 12. Migration / Large-Scale Transformation Task Interface

**Purpose**\
Transform codebase from one supported state to another.

### Required Inputs

- Migration plan

### Execution Scope

**Scope**: defined migration partition

**Permissions**

- Edit
- Rename
- Modify configs

### Constraints

**Invariants**

- Maintain compatibility where required

### Validation

- Impacted tests

### Outputs

- Migrated code

### Success Criteria

- Target partition migrated

### Uncertainty Mode

Generative

---

# 13. Policy / Compliance Task Interface

**Purpose**\
Bring repository into compliance with policy requirements.

### Required Inputs

- Compliance requirement

### Execution Scope

**Scope**: policy-relevant files

### Permissions

- Read
- Edit

### Constraints

**Invariants**

- Preserve functionality where possible

### Validation

- Policy checks

### Outputs

- Remediation changes

### Success Criteria

- Policy violations resolved

### Uncertainty Mode

Verification-led

---

# 14. Proposal / Patch-Synthesis Task Interface

**Purpose**\
Generate a change proposal without applying it.

### Required Inputs

- Change request

### Execution Scope

**Scope**: relevant modules

### Permissions

- Read
- Produce patch

### Constraints

**Invariants**

- Repository must remain unchanged

### Validation

- Optional static checks

### Outputs

- Patch proposal

### Success Criteria

- Actionable proposal produced

### Uncertainty Mode

Generative

---

# Cross-Cutting Execution Controls

Cross-cutting execution controls are **additional parameters applied to a task interface that modify how the repo-agent executes the task**. They do not change the responsibility domain or task class itself. Instead, they constrain the authority, risk envelope, and validation behavior of the agent while performing the task.

In other words:

- **Task interfaces describe what work the agent performs.**
- **Execution controls describe how the agent is allowed to perform that work.**

These controls are called *cross-cutting* because the same parameters apply across many task classes. A bug-fix task, refactor task, feature implementation task, or migration task may all use the same execution controls.

Conceptually the task contract becomes:

```text
Task = (
  Intent,
  Inputs,
  Execution Scope,
  Constraints,
  Validation,
  Outputs,
  Success Criteria,
  Uncertainty Mode

  + Execution Controls
)
```

Execution controls therefore act as **policy parameters supplied by the orchestrator** that determine how aggressively the agent may operate, what level of mutation authority it has, and how much validation must occur before the task is considered complete.

---

## Example: Bug Fix Task

The task interface defines the work to be done:

```text
Intent: Corrective / Bug-Fix
Inputs: failing test
Execution Scope:
  Scope: payments/**
  Permissions: Edit, Modify tests
Constraints:
  Invariants: public API preserving
```

Execution controls then determine **how the repo-agent performs the work**:

```text
ApplyMode: Propose patch only
RiskTier: Medium
ValidationDepth: Impacted tests
ScopeExpansionPolicy: Expand with justification
```

The task remains a **bug fix**, but the execution controls determine:

- whether the agent may mutate the repository
- how far it may explore beyond the initial scope
- how much validation must be performed
- the acceptable operational risk

---

## Why Execution Controls Exist

Without execution controls, the task interface alone cannot express operational policy.

For example, the same bug fix might run under different operational regimes depending on where it appears in the engineering workflow.

### Exploratory investigation

```text
ApplyMode: Analyze only
ValidationDepth: None
RiskTier: Low
```

The agent investigates the issue and produces evidence without modifying the repository.

### Automated remediation

```text
ApplyMode: Apply + validate
ValidationDepth: Impacted tests
RiskTier: Medium
```

The agent may directly apply a patch and run validation to confirm the fix.

### Human review workflow

```text
ApplyMode: Propose patch only
ValidationDepth: Static checks
RiskTier: Medium
```

The agent produces a candidate patch for human review but does not modify the repository.

In all cases the **task itself is unchanged**. Only the **execution authority granted to the agent differs**.

---

## Execution Control Parameters

### A. Apply Mode

Determines whether the agent may mutate the repository and how far the execution should proceed.

- Analyze only
- Propose patch only
- Apply patch only
- Apply + validate
- Apply + validate + summarize

### B. Scope Expansion Policy

Defines how the agent may expand beyond the initial scope defined in the task interface.

- Fixed scope
- Expand within dependency radius
- Expand with explicit justification
- Unrestricted within repo

### C. Risk Tier

Defines the acceptable operational risk and blast radius of the task.

- Low: local, reversible, low blast radius
- Medium: cross-module or contract-adjacent
- High: public API, schema, security, CI/build, or broad refactors

### D. Validation Depth

Specifies how much validation must occur before the task is considered complete.

- None
- Static checks only
- Targeted tests
- Impacted tests
- Full suite
- Benchmarks / repeated-run / soak checks

### E. Invariant Presets

Reusable invariant bundles that can be attached to tasks.

- Behavior preserving
- Public API preserving
- Dependency preserving
- Performance non-regression
- Test-only mutation
- Docs-only mutation
- Config-only mutation

---

# Compact Router View

| Class                                  | Primary Intent                    | Typical Mutation Level     | Default Uncertainty            | Default Success Signal                  |
| -------------------------------------- | --------------------------------- | -------------------------- | ------------------------------ | --------------------------------------- |
| Diagnostic / Root-Cause                | explain failure or regression     | none / minimal             | Diagnostic                     | evidenced root cause                    |
| Review / Verification                  | evaluate existing change          | none                       | Verification-led               | findings + disposition                  |
| Feature Implementation                 | add behavior                      | moderate                   | Closed-form / Generative       | acceptance criteria met                 |
| Corrective / Bug-Fix                   | restore intended behavior         | minimal to moderate        | Diagnostic → Closed-form       | bug resolved + regression guard         |
| Refactor / Structural Transformation   | improve structure                 | moderate to broad          | Closed-form / Exploratory      | structure improved, semantics preserved |
| Optimization / Non-Functional          | improve measurable property       | minimal to moderate        | Exploratory / Closed-form      | metric improved                         |
| Test / Verification Assets             | strengthen automated checks       | tests-focused              | Closed-form                    | reliable verification added             |
| Observability / Instrumentation        | increase diagnosability           | minimal                    | Closed-form                    | actionable telemetry added              |
| Tooling / DX                           | improve engineering workflow      | moderate                   | Exploratory / Closed-form      | friction reduced                        |
| Dependency / Build / Infra Repo        | maintain build/runtime substrate  | moderate to broad          | Closed-form / Exploratory      | build/policy target achieved            |
| Documentation / Knowledge              | improve repo knowledge artifacts  | docs-focused               | Closed-form                    | gap resolved accurately                 |
| Migration / Large-Scale Transformation | move to new supported state       | broad                      | Generative + Closed-form       | target partition migrated safely        |
| Policy / Compliance / Guardrail        | satisfy governance constraints    | minimal to broad           | Verification-led / Closed-form | finding resolved with evidence          |
| Proposal / Patch-Synthesis             | prepare change without full apply | none / patch artifact only | Generative / Exploratory       | actionable proposal produced            |

---

# Notes on Use

This taxonomy is best used as a machine-facing layer under simpler human-facing labels. A caller may present a task as “fix”, “feature”, or “refactor”, while the execution system maps it to one of the classes above plus the cross-cutting controls.

A practical request format can therefore be:

```text
Human label: fix
Class: Corrective / Bug-Fix
Apply mode: Apply + validate
Scope: payments/tests/** + payments/src/retry.py
Permissions: edit source, edit tests, execute commands; no deps
Invariants: public API preserving
Validation: targeted tests + 20x repeated flaky test run
Success: no repro in repeated runs; targeted suite passes
Budget: <= 6 files, <= 300 changed lines
```

This gives the container enough structure to act safely without forcing every caller to fully author the underlying schema from scratch.

---

# Node Execution (Container) Profile

The **Node Execution (Container) Profile** defines the runtime capabilities and configuration of the repo‑agent container used to execute a task. While the **Task Interface** specifies *what work should be performed*, and **Execution Controls** specify *how aggressively or cautiously the work should be performed*, the **Container Profile** specifies *what capabilities the agent actually has available in order to perform the work*.

Conceptually a repo‑agent node invocation consists of three parts:

```text
Node Invocation
   ├─ Task Interface (what work to perform)
   ├─ Execution Controls (how to perform it)
   └─ Container Profile (runtime capabilities available)
```

This separation is important because:

- The **same container profile may serve many task interfaces**.
- The **same task interface may run under different container profiles** depending on node policy.

For example, a feature implementation task may run in a restricted container for safety or a more capable container during local development.

## Container Profile Components

A container profile typically specifies the runtime environment available to the repo‑agent container, including:

### System Instructions

Base system prompt or operational instructions used to guide the agent's behavior.

Examples:

- "Investigate failures without modifying production code"
- "Implement features safely within constraints"

### Available Tools

Tools installed or made available inside the container.

Examples:

- git
- test runner
- linters / formatters
- build tools
- database migration tools

### Repository Mount Configuration

How the repository is mounted into the container.

Examples:

- read‑only repository
- writable working tree
- detached branch
- temporary workspace

### Network Access

External connectivity permitted to the container.

Examples:

- disabled
- internal package registries only
- unrestricted

### Secrets / Credentials

Sensitive credentials available to the container when required.

Examples:

- package registry tokens
- deployment credentials
- database access tokens

### Environment Variables

Configuration parameters passed into the container runtime.

Examples:

- runtime configuration flags
- feature flags
- tool configuration

### Resource Limits

Operational resource constraints placed on the container.

Examples:

- CPU limits
- memory limits
- execution timeout

## Example Node Configuration

```text
Node: FeatureImplementation

Task Interface
  Inputs: feature spec
  Execution Scope: module X
  Constraints: preserve public API

Execution Controls
  ApplyMode: Propose patch only
  ValidationDepth: Impacted tests

Container Profile
  Tools: git, test runner, formatter
  Network: disabled
  Secrets: none
  System Instructions: "Implement features safely within constraints"
```

This structure allows orchestration systems such as **Archipelago** to reuse the same base repo‑agent container across many node types while customizing behavior through task parameters, execution controls, and container profile configuration.

