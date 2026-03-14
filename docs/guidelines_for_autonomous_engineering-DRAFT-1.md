# Strategy for Autonomous Software Engineering

## Goal

To build software autonomously with LLM-based agents in a way that is reliably correct, economically efficient, hard to game, and continuously learning.

Expanded, this means building a system that:

- delivers the right behavior
- preserves evolvability and design quality
- generates trustworthy evidence that the work is correct
- resists proxy optimization and self-deception
- becomes more informed over time about requirements, architecture, and failure modes

A sharper phrasing is: **maximize trustworthy software progress per unit of time and compute.**

## Diagnosis

The central challenge is not primarily getting LLM-based agents to generate code. They can already do that. The challenge is building a system in which fast-generating agents produce **trustworthy progress rather than plausible-looking artifacts**.

Critical aspects of the situation include:

1. **LLMs are strong generators but weak self-governors.** They can produce specs, tests, code, and plans quickly, but they do not reliably enforce the right standards on themselves. Left poorly constrained, they optimize for local success signals.

2. **Proxy metrics are easy to satisfy dishonestly.** “Tests pass,” “spec addressed,” “task completed,” and “coverage increased” can all be gamed or satisfied shallowly unless inspection is independent and criteria are precise.

3. **Requirements are not fixed inputs; they are discovered during development.** Software engineering is partly a learning process. The system must surface ambiguity, mistaken assumptions, and specification gaps, not just execute instructions.

4. **Software quality is multi-dimensional and often in tension.** Correct behavior, good design, evolvability, speed, cost, and anti-gaming robustness do not naturally align. Optimizing one can degrade another unless the system is deliberately shaped.

5. **Control structure matters more than raw model capability.** The key question is not just how smart the agents are, but who can modify what, who judges success, how artifacts flow, and where independent pressure comes from.

6. **Bad outputs can compound over time.** Weak tests, poor design, or mistaken specs do not just create isolated defects; they distort later work. Autonomous systems can scale these errors quickly.

7. **Additional agents are not automatically a solution.** More agents can improve independence, but they also add coordination cost, conflict, noise, and complexity. Architectural complexity must earn itself.

8. **The right design is domain- and stage-dependent.** Early-stage systems may need the strongest pressure on behavioral correctness; later-stage systems may need more structural pressure. There is no one best arrangement across all contexts.

In summary: **autonomous software engineering is a control problem under uncertainty, not just a generation problem**. The core difficulty is creating a system in which LLM-based agents learn the right things, apply pressure to the right risks, and cannot easily convert apparent progress into false progress.

## Guiding Policies

### 1. Treat autonomous software engineering as a control problem, not just a generation problem

Design the system around authority, incentives, permissions, inspection, and feedback—not only around the ability of agents to generate artifacts.

### 2. Anchor success in externally checkable outcomes

Prefer observable evidence over internal narratives, self-reported completion, or easily gamed proxy metrics. Success should be grounded in outcomes that can be checked against reality or other externally inspectable evidence, regardless of who performs the check.

### 3. Separate powers so no critical actor can define and satisfy its own success

Do not allow a critical actor to both produce an artifact and be the authority that judges whether the evidence is sufficient to accept that artifact. This applies to specifications, tests, code, and evaluation. The purpose of this policy is to ensure that externally checkable outcomes are not interpreted, filtered, or accepted solely by the actor whose work is being checked.

### 4. Apply the strongest independent pressure to the most important current risk

The system should direct its strongest independent checking pressure at the defect class that is most catastrophic at the current stage of development.

### 5. Prefer the simplest architecture that can learn, and treat architectural choices as empirical hypotheses

Start with the simplest control structure that can produce trustworthy progress and useful learning. Treat architectural additions and changes as empirical hypotheses: make their assumptions explicit, monitor the failure modes they are meant to address, and add complexity only when observed evidence shows it is needed.

### 6. Optimize the system for learning over time, not just immediate throughput

The system should not merely produce artifacts quickly. It should improve understanding of requirements, architecture, failure modes, and the limits of its own current design.

## Coherent Actions

The following actions are designed to work together. They translate the guiding policies into an operating model for autonomous software engineering.

### 1. Build the system around an explicit artifact flow

**Carries out Policies:** 1, 2, 6\
**How:** It turns the system into a controllable workflow with inspectable handoffs, grounds progress in concrete outputs, and creates a structure from which the system can learn.

Define a small set of primary artifacts and standard handoffs between them, such as:

- intent / requirement
- shared specification
- tests
- implementation
- evaluation results
- decision and learning records

Each stage should consume concrete artifacts and produce concrete artifacts. This makes the system easier to inspect, constrain, and improve.

### 2. Assign authority, roles, and permissions to match the artifact flow

**Carries out Policies:** 1, 3  
**How:** It makes control structure explicit, keeps roles narrow and well-aligned, and prevents critical actors from both producing and accepting the same class of artifact.

For each artifact, define:

- who may read it
- who may write it
- who may review it
- who may accept it

Use repository permissions and workflow enforcement so that role boundaries are structurally real. Define roles narrowly, with a small number of aligned objectives, and avoid combining intent definition, implementation planning, test design, and acceptance authority in one role. In particular, do not allow the same critical actor to both produce and accept the same class of artifact.

### 3. Keep a shared specification layer central, but shape it to the work

**Carries out Policies:** 1, 4, 6\
**How:** It gives the system a stable control reference, helps direct pressure toward the right risk for the current change type, and improves learning by making intent explicit.

Maintain a shared specification that acts as the source of truth for behavior, constraints, and scope. Vary the shape of the specification by change type:

- feature work: new behavior and edge cases
- bug fixes: failing behavior and regression expectation
- refactors: behavior-preservation boundaries
- performance/security/reliability work: measurable constraints

The specification should constrain intended outcomes without over-prescribing internal implementation unless that decision is intentional.

### 4. Separate generation from evaluation and make evaluation independently meaningful

**Carries out Policies:** 2, 3\
**How:** It grounds acceptance in externally checkable evidence and ensures that evidence is not solely interpreted by the actor whose work is being judged.

Design the system so that artifact generation and artifact evaluation are distinct functions. Evaluation should rely on evidence that is externally checkable and not easily reduced to self-reported completion.

Examples include:

- test outcomes
- precise acceptance criteria
- regression results
- mutation results
- static analysis results
- benchmark or security results where relevant

### 5. Apply the strongest independent pressure to the highest current risk

**Carries out Policies:** 4, 5\
**How:** It focuses scarce independence and complexity where they matter most, and treats the choice of pressure as something to be adapted as evidence accumulates.

Identify the defect class that is most dangerous at the current stage of the product and place the strongest independent checking pressure there.

Examples:

- early-stage product: behavioral correctness
- later-stage or scaling system: structural integrity, performance, or maintainability
- security-sensitive domain: exploitability and misuse resistance

This pressure should influence the architecture, agent roles, and evaluation emphasis.

### 6. Define explicit rubrics for quality-critical artifacts

**Carries out Policies:** 2, 6\
**How:** It turns vague quality expectations into checkable standards and helps the system learn what good artifacts actually look like.

Do not leave artifact quality implicit. Create rubrics for artifacts that strongly influence downstream quality, especially:

- specifications
- tests
- code changes
- reviews

For tests, rubrics may include:

- precise assertions
- narrow error expectations
- meaningful edge-case coverage
- appropriate branch/path coverage
- traceability to specification or bug report

### 7. Preserve traceability across the full loop

**Carries out Policies:** 1, 2, 6\
**How:** It makes the control structure auditable, ties success claims to evidence, and preserves the information needed for cumulative learning.

Maintain links between:

- requirements and specifications
- specification clauses and tests
- tests and code changes
- failures and fixes
- design decisions and later outcomes

Traceability supports inspection, debugging, learning, and later architectural adaptation.

### 8. Introduce structured tension where independent pressure is needed

**Carries out Policies:** 3, 4, 5\
**How:** It creates independence where gaming risk or blind spots justify it, while keeping additional roles contingent on evidence rather than adding them by default.

Use separate roles or review functions when independence materially improves quality, especially where gaming risk is high. But do this selectively rather than reflexively. Independent pressure should be introduced where it closes a real control gap.

### 9. Start with the simplest viable control structure and evolve it empirically

**Carries out Policies:** 1, 5, 6\
**How:** It keeps the architecture simple enough to operate, frames additions as hypotheses, and uses observed outcomes to improve the system over time.

Begin with the minimum architecture that can deliver trustworthy progress. Treat additions—new agents, new reviews, new checks, new permissions—as responses to observed failure modes rather than default features.

For each major architectural addition:

- state the problem it is meant to solve
- define the assumption behind it
- monitor whether it reduces the targeted failure mode
- remove or revise it if it does not justify its cost

### 10. Optimize each cycle to produce learning, not just output

**Carries out Policies:** 5, 6\
**How:** It ensures the workflow improves both the product and the engineering system itself, rather than merely generating more artifacts.

Design the workflow so each cycle improves understanding of:

- the requirement
- the specification
- the architecture
- the defect patterns
- the limits of the current system design

This requires surfacing ambiguities, recording rationale, and treating failures as information for improving both the product and the engineering system.

## Design Principle

A guiding design principle for an autonomous software engineering system is to make the desired outcome the easiest equilibrium for the system to reach.

This means shaping the system so that the cheapest, most natural path for agents is also the correct path.

How to apply this in practice:

- **Permissions:** make it impossible or costly for a coding agent to edit tests, so fixing code is easier than weakening checks.
- **Artifact flow:** require spec → tests → code → evaluation, so skipping steps is harder than following them.
- **Rubrics:** define good tests explicitly, so vague tests are flagged instead of silently accepted.
- **Independent acceptance:** make another role or process accept evidence, so self-serving interpretations do not close the loop.
- **Feedback loops:** surface failures and ambiguities quickly, so learning is easier than pushing forward with false certainty.

A useful design test is: when an agent faces pressure, what is the easiest way for it to succeed?

- If the answer is “game the metric,” the equilibrium is wrong.
- If the answer is “produce a better artifact that survives independent checks,” the equilibrium is better.

## Example: Applying the Strategy to TDD Agent Decomposition

This example applies the strategy to one important software engineering workflow. It is not intended to imply that the same agent structure is optimal across all domains or all forms of autonomous work; the right design remains dependent on failure costs, observability, inspectability, pace of change, and gaming risk.

### Problem

A system using a spec agent followed by a coding agent produced useful output, but the unit tests were often substandard. Common weaknesses included:

- loose assertions
- broad error assertions
- missing branch coverage
- risk of an agent changing tests to make code appear acceptable

### Design Response

The TDD loop was redesigned around clearer control structure and clearer role boundaries.

Key moves:

- separate test writing from code writing
- keep the shared specification central
- use black-box testing pressure as the default because behavioral correctness is the most catastrophic early defect class
- prevent the coding agent from editing tests
- preserve the option to add more structural pressure later only if evidence justifies it

### Resulting Principle Demonstrated

This example shows that the highest-value move is often not “add more agents,” but rather:

- clarify objectives
- narrow roles
- separate authorities
- enforce permissions
- make the system easier to inspect and harder to game

## Practical Heuristics

When deciding whether to add or split agents, ask:

- What exact failure mode is this change meant to reduce?
- Is that failure mode already mitigated elsewhere?
- Does this new agent add unique signal or mostly duplicate signal?
- Can the same benefit be achieved more cheaply with permissions, rubrics, or tooling?
- Does this change improve learning, or only increase output?
- Does it align with model strengths: concrete artifacts, short loops, and clear criteria?

## Anti-Patterns to Avoid

- one role defining intent, designing tests, planning implementation, and judging success
- weak or implicit quality criteria
- agents that can modify the artifacts that are supposed to constrain them
- excessive agent proliferation without clear marginal value
- architectures optimized for passing signals rather than learning or correctness
- relying on cooperation where independent pressure is required

## Closing Principle

A good autonomous engineering system is one in which:

- the desired behavior is clearly defined
- the strongest pressures are placed on the most important risks
- no critical actor can easily redefine its own success
- the system becomes more informed as it operates
- added complexity must justify itself empirically

