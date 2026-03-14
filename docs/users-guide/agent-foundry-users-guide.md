# Agent Foundry Users Guide

## CLAUDE.md Layering

There are at least three layers of CLAUDE.md files in the system, serving different audiences at different times:

### Layer 1: Agent Foundry repo CLAUDE.md

- **Audience**: agent working on the platform itself
- **When**: developing/fixing agent_foundry and archipelago code
- **Content**: dev practices, TDD workflow, LSP rules, module conventions
- **Location**: `/CLAUDE.md` at the root of the agent-foundry repo

### Layer 2: Container-baked CLAUDE.md

- **Audience**: Claude Code running inside a container
- **When**: container starts, before any task-specific work
- **Content**: marker protocol, completion protocol, design principles, working style
- **Location**: `docker/CLAUDE.md`, baked into the Docker image at `/home/claude/.claude/CLAUDE.md`
- **Owned by**: the product (Archipelago's is different from a future knowledge system's)

### Layer 3: Project/node-specific CLAUDE.md

- **Audience**: same Claude Code instance, same session
- **When**: loaded after repo clone, layered on top of the baked CLAUDE.md
- **Content**: repo-specific conventions, test patterns, architecture decisions
- **Location**: `.claude/CLAUDE.md` inside the cloned target repo
- **Owned by**: the target repo, not by Agent Foundry or the product

### Risks as layers multiply

- **Contradictions** between layers (Layer 2 says "TDD always", Layer 3 repo says "no tests for scripts")
- **Staleness** when platform conventions change but baked CLAUDE.md files don't get rebuilt
- **Bloat** — each layer adds to the context window the agent consumes at session start

### Open question: precedence

This is essentially work-status item 19 — the two-layer CLAUDE.md strategy — but it's actually three layers now. Worth defining a precedence rule: does Layer 3 override Layer 2? Does Layer 2 override Layer 1? Or do they merge? How are contradictions resolved?
