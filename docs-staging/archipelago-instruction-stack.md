# Archipelago Instruction Stack

## What is an instruction stack?

An Archipelago agent receives instructions from multiple sources. These sources form a stack — ordered from most stable and general at the bottom to most ephemeral and specific at the top. Each layer adds specificity without contradicting the layers below it. The agent sees the composed result of all layers.

## Why this is critical

Archipelago's agents are autonomous. They make decisions — what to write, how to structure it, when to stop — based entirely on the instructions they receive. There is no human reviewing every action in real time. The instruction stack is the primary control mechanism.

If the stack is wrong, the consequences are silent and compounding:

- A missing permission constraint means the agent writes where it shouldn't. The violation isn't caught until downstream evaluation or, worse, production.
- A contradictory instruction between layers means the agent picks one interpretation unpredictably. The same agent may behave differently across runs.
- A missing project convention means the agent produces code that is correct but inconsistent with the codebase. Integration friction accumulates.
- A missing lesson from a prior cycle means the agent repeats a known mistake. The system fails to learn.

The instruction stack must be explicit, composable, and testable. Every layer must have a clear owner, a defined scope, and a mechanism for verification.

## The challenge

Claude Code reads instructions from CLAUDE.md files, system prompts, and task prompts. These are concatenated — there is no scoping, priority system, or conflict resolution. If two layers say contradictory things, the model resolves the conflict implicitly based on recency, specificity, or randomness. The system designer has no guarantee about which instruction wins.

This means:

- **Layer ordering matters.** It is plausible that later instructions override earlier ones, but this has not been empirically verified for Claude Code's instruction processing. The concatenation order of CLAUDE.md files (global, project, directory) and how Claude resolves conflicts between them is not documented. This must be tested empirically before relying on ordering as a conflict resolution mechanism.
- **Contradictions must be prevented by design.** There is no runtime conflict resolver. Each layer must be written with awareness of what the other layers say.
- **Omissions are invisible.** If a layer is missing, the agent proceeds without it. There is no error. The failure mode is wrong behavior, not a crash.
- **Testing the composed result is essential.** It is not enough to test each layer in isolation. The full composed instruction set must be verified for completeness, consistency, and correctness.

## The layers

Listed from most stable (bottom) to most ephemeral (top):

### 1. Agent Foundry base image

**Owner:** Agent Foundry platform
**Scope:** Universal agent protocol, infrastructure, tool usage
**Mechanism:** CLAUDE.md baked into the base Docker image (`acp-cc-worker`). **Not yet implemented** — the base image currently has no CLAUDE.md.
**Status:** To be created at `src/agent_foundry/acp/docker/CLAUDE.md`

Contains:
- Clarification request protocol: when the agent encounters ambiguity or needs input, emit `CLAUDE_CODE_CLARIFICATION_REQUEST` with a structured JSON payload
- Permission request protocol: when the agent needs authorization for a risky action, emit `CLAUDE_CODE_PERMISSION_REQUEST` with a structured JSON payload
- LSP-first code navigation rules
- Tool usage conventions
- Working directory constraints (`/workspace` only)

Does **not** contain task completion semantics — the definition of "done" is product-specific.

This layer changes only when the Agent Foundry platform changes. It is the same for every product built on Agent Foundry.

### 2. Archipelago system-wide

**Owner:** Archipelago product
**Scope:** Software engineering discipline, quality standards, task completion protocol
**Mechanism:** Baked into the Archipelago Docker image, appended to the base image CLAUDE.md

Contains:
- Software design principles (coherence, separation of concerns, information hiding)
- TDD discipline (write tests first, atomic commits)
- Commit conventions
- Task completion protocol: emit `ARCHIPELAGO_TASK_COMPLETE` when all work is done, tests pass, and changes are committed

This layer changes when Archipelago's engineering standards change. It is the same for every role within Archipelago.

### 3. Role-specific

**Owner:** Archipelago product (per role definition)
**Scope:** What this role does, what it can access, how it completes its task
**Mechanism:** Appended to CLAUDE.md at container startup via `ACP_ROLE_INSTRUCTIONS_PATH`

Contains:
- Role identity ("You are a unit test writer")
- Scope constraints ("Work only in `tests/`. The `src/` directory is not accessible.")
- Task completion criteria specific to the role
- Quality rubric criteria relevant to the role's output

This layer changes when the role definition changes. It differs between the unit test writer, code writer, spec author, etc.

### 4. Project-specific

**Owner:** The target repository
**Scope:** Codebase conventions, architecture, testing patterns
**Mechanism:** The repo's own `.claude/CLAUDE.md`, read by Claude Code automatically after cloning

Contains:
- Coding conventions (naming, structure, patterns)
- Test framework and patterns
- Architecture constraints
- Dependencies and toolchain
- Project-specific rules ("never mock the database", "all API routes must have integration tests")

This layer is not controlled by Archipelago — it comes from the repo being worked on. Archipelago must respect it without knowing its contents in advance.

### 5. Learned lessons

**Owner:** Archipelago learning loop
**Scope:** Accumulated observations from prior cycles
**Mechanism:** TBD — options include appending to CLAUDE.md, including in the task prompt, or writing to a lessons file in the workspace

Contains:
- Ambiguity patterns discovered in prior slices
- Specification clauses that caused difficulty
- Codebase integration friction points
- Defect patterns (which rubric criteria fail most often)
- Convention detection results

This layer grows over time. It is specific to the project and accumulates across cycles.

### 6. Task prompt

**Owner:** Archipelago orchestrator (the handler)
**Scope:** The specific work unit being executed
**Mechanism:** Sent as the initial prompt via WebSocket InputMessage

Contains:
- The slice or feature spec
- Acceptance criteria
- Test commands
- Dependencies on prior slices
- Gate Controller feedback (on revision cycles)

This layer is unique per invocation. It is the most specific and most ephemeral.

## Open questions

- How should layers 1 and 2 compose? Currently layer 2 overwrites layer 1. Should the base image have its own CLAUDE.md that layer 2 appends to?
- How should learned lessons be delivered? As a CLAUDE.md layer, as part of the task prompt, or as a file in the workspace?
- Should the composed instruction set be logged or captured for debugging? When an agent misbehaves, can we reconstruct exactly what instructions it received?
- How do we test the composed result? Can we write assertions against the full instruction text that an agent sees at startup?
