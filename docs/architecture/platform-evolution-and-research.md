# Platform Evolution & Research

## Feedback Loop

Systems built on Agent Foundry produce reusable components. These push down into the platform, strengthening all systems.

```
Archipelago builds systems
        │
        ▼
Systems produce reusable components
        │
        ▼
Components push down into Agent Foundry
        │
        ▼
Agent Foundry strengthens all systems
        │
        └──────► (repeat)
```

Examples of components that will migrate from Archipelago into Agent Foundry:

- **Docker worker image**: The Claude Code execution environment (image, entrypoint, capability stack) is currently Archipelago-specific, but any Agent Foundry system that needs an autonomous Claude worker uses the same infrastructure.
- **Adapter protocol**: The WebSocket-based communication between container and orchestrator is not specific to software development.
- **WorkerManager**: Container lifecycle, session persistence, and turn-taking are general orchestration concerns.

## Worker Capability Stack

The "capability stack" is the full set of configuration, skills, hooks, and instructions baked into the Docker image that transforms a generic Claude Code installation into an autonomous worker.

| Layer | Location in image | Purpose |
|-------|------------------|---------|
| CLAUDE.md | `/home/claude/.claude/CLAUDE.md` | Role, design principles, task completion protocol, working style |
| Skills | `/home/claude/.claude/skills/` | Reusable behaviors (e.g. lessons-learned) |
| Settings | `/home/claude/.claude/settings.json` | Claude Code configuration |
| Entrypoint | `/home/claude/entrypoint.sh` | Auth, git credentials, repo clone, adapter launch |
| Adapter | `/home/claude/adapter.py` | WebSocket protocol bridge between Claude CLI and orchestrator |

The capability stack includes:

- **Software design principles** — coherence, separation of concerns, abstractions, information hiding
- **Task completion protocol** — the sequence Claude must follow: verify requirements, run tests, commit, push, log lessons, then emit `ARCHIPELAGO_TASK_COMPLETE`
- **Clarification protocol** — structured markers (`ARCHIPELAGO_NEED_CLARIFICATION`, `ARCHIPELAGO_NEED_PERMISSION`) that the adapter translates into typed protocol messages
- **Lessons-learned skill** — at task completion, Claude reviews its session and appends useful observations to `/workspace/.claude/lessons-learned.md`

## Cognitive Reasoning Research

The quality of autonomous work depends on the reasoning capabilities of the underlying model. We maintain an eval suite based on a taxonomy of 28 cognitive elements from "Cognitive Foundations for Reasoning and Their Manifestation in LLMs" (Kargupta et al., 2025), following Anthropic's agent eval methodology.

This research feeds back into the platform:

- **System instructions**: Findings about which cognitive elements models struggle with inform how we write CLAUDE.md and prompt construction across Agent Foundry
- **Model selection**: Eval scores guide which models are suitable for which types of autonomous work
- **Capability stack design**: Understanding model strengths and weaknesses shapes what we put in the capability stack to compensate or amplify
