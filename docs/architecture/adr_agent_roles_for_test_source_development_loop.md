# ADR: Agent Roles for the Test Writing / Source Writing Loop

## Status

Draft



## Objective

Decide which agents should participate in the **test-first / implementation-second loop** of an agentic software development system.

The goal is to determine how the system applies pressure toward:

- behavioral correctness
- structural correctness
- robustness against gaming
- fidelity to intended behavior rather than proxy metrics
- convergence speed of the TDD loop

This is an architectural decision because it defines a core control structure of the development system: who generates tests, who generates implementation, and how correctness pressure is distributed across agents.

## Development Model Assumption

This ADR assumes **test-driven development (TDD)** as the governing development process.

Under this model:

1. Tests are written **before implementation**.
2. Implementation is written **to satisfy failing tests**.
3. The loop proceeds iteratively until the specification is satisfied and all tests pass.

Therefore the architecture being decided here governs **who writes tests first**, **who writes implementation in response**, and **how adversarial pressure is distributed during the TDD loop**.

## Guiding Principles

- In the early life of the system, incorrect behavior is the more catastrophic defect class, because it directly invalidates the product before structural quality has a chance to matter.

## Decision Scope

This ADR covers the **agent arrangement used inside the TDD loop**.

The loop assumed by this document is:

1. specification interpreted
2. tests generated
3. implementation written to satisfy tests
4. failures analyzed
5. new tests or implementation revisions generated

This ADR does **not yet decide**:

- the exact protocol between agents
- escalation / arbitration behavior
- termination criteria
- model selection
- compute budgets
- repository permissions

## Options Under Consideration

### Option 1: Coding Agent + White-Box Testing Agent

TDD flow:

1. White-box testing agent writes tests **first** with visibility into source code structure.
2. Tests initially fail.
3. Coding agent writes implementation to satisfy the tests.

The white-box testing agent can read source code and use structural signals such as:

- branches
- control flow
- state transitions
- invariants

Primary pressure introduced:

- structural correctness
- branch/path targeting
- internal invariant enforcement

Primary risk:

- weaker independent behavioral validation
- tests may become tightly coupled to implementation structure

### Option 2: Coding Agent + Black-Box Testing Agent

TDD flow:

1. Black-box testing agent writes tests **first** without visibility into source code.
2. Tests initially fail.
3. Coding agent writes implementation to satisfy externally defined behavior.

The black-box testing agent operates only from:

- the shared specification
- public interfaces
- observable outputs

Primary pressure introduced:

- externally observable behavior
- contract fidelity
- resistance to implementation-shaped tests

Primary risk:

- weaker structural coverage
- poorer targeting of hidden failure surfaces

### Option 3: Coding Agent + White-Box Testing Agent + Black-Box Testing Agent

TDD flow:

1. Black-box agent generates behavior-driven tests from the specification.
2. White-box agent generates structure-aware tests using source visibility.
3. Tests fail.
4. Coding agent implements behavior to satisfy both test suites.

Primary pressure introduced:

- behavioral correctness
- structural correctness
- reduced correlated blind spots

Primary risk:

- coordination overhead
- conflicting tests
- higher compute cost

## Decision: Option 2

Following the comparison described in **Option 1 vs Option 2**, the architecture adopts **Option 2 (Coding Agent + Black-Box Testing Agent)** as the baseline design. The remaining question is whether adding a white-box testing agent (Option 3) provides enough additional value to justify its cost and complexity.

### Reasoning

Option 3 is a strict superset of Option 2. It introduces additional structural pressure by allowing a white-box testing agent to generate tests informed by internal implementation details. In principle this could expose structural weaknesses earlier in the development loop.

However, Option 3 also introduces additional system complexity:

- additional agent coordination
- potential conflict between black-box and white-box test suites
- higher compute cost
- more complex arbitration and debugging

Because Option 2 already provides strong behavioral validation—the defect class identified as most catastrophic early in the life of the system—the burden of proof lies with Option 3 to demonstrate that its additional structural intelligence produces **materially better outcomes**.

### Empirical Approach

The decision therefore follows an empirical strategy:

1. Adopt **Option 2** as the default architecture.
2. Deploy structural mitigations outside the TDD loop.
3. Observe system behavior over time.

Evidence that would justify introducing a white-box testing agent includes:

- repeated defects rooted in hidden structural coupling
- structural regressions escaping existing mitigations
- maintainability degrading faster than expected
- structural problems discovered too late in the lifecycle

If such patterns appear consistently, the system may introduce a white-box testing agent and move toward **Option 3**.

Until such evidence exists, Option 2 remains preferred because it delivers the most important early pressure (behavioral correctness) with lower architectural complexity.

## Option 1 vs Option 2

After evaluation, the decision is to **prefer Option 2: Coding Agent + Black-Box Testing Agent**.

### Rationale

A guiding principle for this ADR is that **behavioral correctness is the most critical defect class in the early life of a system**. If the system behaves incorrectly relative to its specification, the product is effectively invalid regardless of how well structured the internal implementation may be.

Option 2 creates strong pressure on the dimension that matters most at this stage:

- externally observable correctness
- fidelity to the shared specification
- resistance to implementation-shaped tests

Because the black-box testing agent has no visibility into the source code, it cannot tailor tests to the implementation. Tests must instead derive from the specification and observable behavior. This reduces the risk that tests encode incidental implementation details and increases the likelihood that failures represent genuine specification violations.

Option 1, by contrast, prioritizes structural scrutiny. While structural quality is important for long-term evolvability, it is less decisive in determining whether a system successfully reaches or survives the MVP stage.

Therefore, when choosing between the two pressures, the architecture prioritizes **behavioral validation over structural validation**.

### Known Weakness of Option 2

Option 2 introduces a structural blind spot. Because the testing agent does not inspect the source code, it cannot deliberately target:

- unexecuted branches
- hidden state transitions
- inefficient algorithms
- dead code
- fragile internal coupling

As a result, a system could pass all black-box tests while still accumulating structural problems that degrade maintainability and long-term development velocity.

### Mitigations Required for Option 2

To compensate for this weakness, the broader system must introduce **independent structural pressure outside the black-box testing agent**. Examples include:

- static analysis and linting
- strict type systems
- architectural rules or dependency constraints
- code complexity limits
- coverage monitoring
- mutation testing
- periodic structural refactoring passes

These mechanisms help detect structural degradation even though the primary TDD loop focuses on behavioral correctness.

The intent is that **behavioral correctness remains the primary gate for acceptance**, while structural quality is enforced through complementary mechanisms in the surrounding system architecture.

## System Requirements Independent of Option

The system must implement the following regardless of which option is chosen.

### 1. Shared Specification Layer

The system must maintain a **shared specification layer**: a common description of intended behavior that both test generation and implementation are constrained by.

The specification acts as the **source of truth for the TDD loop**.

At minimum it should define:

- required behaviors
- inputs and outputs
- invariants
- error conditions
- edge-case expectations
- non-goals where relevant

Without this layer, tests and implementation may optimize against each other rather than against intended behavior.

### 2. Test-First Enforcement

The system must enforce that **tests are generated before implementation changes**.

Implementation agents should not be able to introduce behavior that is not justified by either:

- the specification
- a failing test derived from the specification

This preserves the TDD discipline.

### 3. Clear Role Boundaries

Each agent must have an explicit role definition including:

- what artifacts it may read
- what artifacts it may write
- what objective it optimizes
- what actions are disallowed

### 4. Independent Failure Pressure

The system must preserve at least one source of testing pressure that the coding agent **cannot weaken by modifying its own success criteria**.

This requirement prevents objective collapse.

### 5. Traceability

The system must trace relationships between:

- specification statements
- generated tests
- failing behaviors
- code changes addressing failures

### 6. Conflict Handling

The system must define what happens when:

- tests contradict the shared specification
- white-box and black-box tests disagree
- implementation passes one test suite but fails another

### 7. Termination Criteria

The system must define what constitutes completion, such as:

- all required tests passing
- specification coverage thresholds
- mutation score thresholds
- no unresolved specification contradictions

### 8. Anti-Gaming Controls

The system must include mechanisms to prevent degeneracy such as:

- immutable or review-gated specs during a loop
- mutation testing
- independent regression suites
- limits on who may modify which tests
- audit logs for test weakening

## Creative Tension as a Design Principle

High-quality creative work is often produced under conditions of **structured tension between capable contributors**. A frequently cited example is the songwriting partnership of John Lennon and Paul McCartney. Their differing styles, mutual critique, and competitive pressure are widely regarded as factors that elevated the quality of their work. The collaboration worked because:

- both contributors were highly capable
- neither fully controlled the outcome
- both operated under shared standards of taste and quality

This pattern suggests a general principle relevant to agentic system design: **quality can emerge from constrained opposition rather than unified optimization**.

The goal is not harmony between roles, and not uncontrolled conflict. Instead the system should create **structured friction under a shared specification** so that weaknesses are exposed and corrected.

The coding/testing agent architecture described in this ADR intentionally applies this principle.

## Tensions Between Coding and Testing Agents

TDD deliberately creates tension between **test creation** and **implementation creation**.

### Coding Agent Pressure

The coding agent is pushed toward:

- eliminating failing tests
- satisfying constraints efficiently
- minimizing implementation complexity
- converging quickly

This pressure can create a risk of optimizing for **passing signals rather than intended behavior**.

### Testing Agent Pressure

Testing agents are pushed toward:

- generating failing tests
- exposing edge cases
- increasing constraint coverage
- rejecting underspecified behavior

This pressure can create risks of:

- over-constraining the implementation
- asserting incidental implementation details
- generating tests detached from real requirements

### Productive Adversarial Balance

A well-designed TDD agent architecture creates productive tension:

- testing agents **open failure surfaces**
- coding agents **close failure surfaces**
- the specification determines which failures are legitimate

The goal is **constrained adversarial pressure**, not unrestricted conflict and not passive cooperation.

## Initial Evaluation Criteria

The options should be evaluated against:

- resistance to gaming
- behavioral correctness pressure
- structural correctness pressure
- speed of TDD convergence
- debugging efficiency
- compute cost
- risk of correlated blind spots
- ease of operating the system
- suitability for high-assurance systems

## Repository Permissions

Given the decision to adopt **Option 2 (Coding Agent + Black-Box Testing Agent)**, repository permissions must enforce the TDD discipline and preserve independence between testing and coding roles.

Proposed permission model:

**Black‑Box Testing Agent**
- Read: shared specification, public interfaces, existing tests
- Write: test files
- Denied: source implementation files

**Coding Agent**
- Read: shared specification, failing tests, existing source code
- Write: source implementation files
- Denied: modification of test files

These permissions ensure:

- tests remain independent of the implementation
- the coding agent cannot weaken tests to satisfy its objective
- the TDD discipline (tests first, implementation second) is structurally enforced

Additional system components (linters, static analyzers, CI checks) may read both code and tests but must not modify them.

## Agent Interaction Protocol

The system will operate a structured TDD loop consistent with the repository permission model.

Proposed protocol:

1. **Specification Interpretation**
   - The black‑box testing agent reads the shared specification.

2. **Test Generation**
   - The testing agent generates new tests derived from the specification.
   - Tests are committed to the repository.

3. **Initial Failure State**
   - The system runs the test suite and confirms failures.

4. **Implementation Phase**
   - The coding agent reads failing tests and existing source code.
   - The coding agent implements behavior required for tests to pass.

5. **Execution and Evaluation**
   - Tests are executed.
   - Results are recorded and traced to the specification.

6. **Iteration**
   - If tests fail, the coding agent revises implementation.
   - If tests pass but specification gaps are detected, the testing agent generates additional tests.

7. **Completion Condition**
   - All tests pass.
   - No unresolved specification coverage gaps remain.

This protocol preserves the empirical loop:

specification → test (prediction) → implementation → observation → revision

and maintains the structured tension between testing and coding agents described earlier in this ADR.

## Architectural Scope Considerations

The discussion in this ADR has largely focused on backend or service-layer code. However, other parts of a software system may be more sensitive to the structural blind spots introduced by Option 2.

In particular, the following components may experience greater risk when relying primarily on black-box testing pressure:

- UI / frontend systems where structural decisions (state management, component composition, rendering paths) strongly influence user-visible behavior
- stateful workflow or orchestration engines
- concurrency-heavy systems
- distributed systems and complex integrations
- performance-critical subsystems
- security-sensitive internals

In these areas, certain failure modes may not surface easily through black-box behavioral tests alone and may only become visible later in the lifecycle. If such patterns emerge, they may constitute evidence supporting the introduction of a white-box testing agent as described earlier in this ADR.

## Open Questions

- Should the shared specification be mutable during a development loop or only between loops?
- Should black-box tests be prevented from reading coverage signals?
- Should white-box tests be allowed to assert implementation details or only invariants?
- What authority resolves disputes between spec, tests, and implementation?
- What metrics best detect test weakening or proxy optimization?

