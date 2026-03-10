# Architecture

## Platform and Product Layers

Agent Foundry is a reusable platform for building agentic AI systems. Products are built on top of it.

```
┌─────────────────────────────────────────────────────────┐
│                    Product Layer                         │
│                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │ Archipelago  │  │  Knowledge  │  │  Future System  │ │
│  │ (autonomous  │  │  Management │  │                 │ │
│  │  software    │  │  (research, │  │                 │ │
│  │  development)│  │  synthesis) │  │                 │ │
│  └──────┬───────┘  └──────┬──────┘  └───────┬─────────┘ │
│         │                 │                  │           │
└─────────┼─────────────────┼──────────────────┼───────────┘
          │                 │                  │
          ▼                 ▼                  ▼
┌─────────────────────────────────────────────────────────┐
│                    Agent Foundry                         │
│                                                         │
│  Capabilities · Handlers · Compiler · Registry ·         │
│  Observability · Docker Worker Image · Execution Layer   │
└─────────────────────────────────────────────────────────┘
```

Agent Foundry never imports from a product package. Products consume Agent Foundry as a dependency. See `docs/agent-foundry-separation-spec.md` for the detailed boundary specification and migration plan.

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

## Archipelago Architecture

Archipelago is an autonomous software development system. It orchestrates Claude Code instances running in Docker containers to implement features, write tests, and commit code.

### Core Interaction Loop

The handler drives a message loop over a WebSocket connection to a Claude Code instance in a container:

```
Orchestrator (handler)                    Container (adapter + Claude Code)
       │                                            │
       │  1. Start container                        │
       │──────────────────────────────────────────►  │
       │                                            │
       │  2. Adapter connects via WebSocket         │
       │  ◄──────────────────────────────────────────│
       │                                            │
       │  3. Send feature spec as InputMessage      │
       │──────────────────────────────────────────►  │
       │                                            │
       │  4. Adapter spawns: claude -p <prompt>     │
       │     --output-format stream-json --verbose  │
       │                                            │
       │  5. Stream OutputMessages (tool use, text) │
       │  ◄──────────────────────────────────────────│
       │                                            │
       │  6a. InterruptMessage (clarification)      │
       │  ◄──────────────────────────────────────────│
       │      Handler prompts human for answer      │
       │      Sends answer as InputMessage          │
       │──────────────────────────────────────────►  │
       │      Adapter: claude -p --resume SESSION   │
       │                                            │
       │  6b. StatusMessage (completed)             │
       │  ◄──────────────────────────────────────────│
       │      Claude emitted ARCHIPELAGO_TASK_COMPLETE
       │      Handler exits loop                    │
       │                                            │
       │  7. (Future) Gate node validates work      │
       │      If rejected: resume with feedback     │
       │      If accepted: send control: terminate  │
       │                                            │
```

### Multi-Turn Sessions

Each prompt to Claude is a separate `claude -p` invocation. Session continuity is maintained via `--resume SESSION_ID`. The adapter captures the session ID from the `system.init` event on the first turn and reuses it for all subsequent turns. This means:

- Each turn is stateless from the CLI's perspective, but Claude retains full context via the session
- An external entity (human, orchestrator, another node) must send each prompt — Claude does not loop autonomously
- This provides natural monitoring points between every turn

### Worker Capability Stack

The Docker image contains everything Claude Code needs to work autonomously. This is the "capability stack" — the full set of configuration, skills, hooks, and instructions baked into the image:

| Layer | Location in image | Purpose |
|-------|------------------|---------|
| CLAUDE.md | `/home/claude/.claude/CLAUDE.md` | Role, design principles, task completion protocol, working style |
| Skills | `/home/claude/.claude/skills/` | Reusable behaviors (e.g. lessons-learned) |
| Settings | `/home/claude/.claude/settings.json` | Claude Code configuration |
| Entrypoint | `/home/claude/entrypoint.sh` | Auth, git credentials, repo clone, adapter launch |
| Adapter | `/home/claude/adapter.py` | WebSocket protocol bridge between Claude CLI and orchestrator |

The capability stack is what transforms a generic Claude Code installation into an autonomous worker. It includes:

- **Software design principles** — coherence, separation of concerns, abstractions, information hiding
- **Task completion protocol** — the sequence Claude must follow: verify requirements, run tests, commit, push, log lessons, then emit `ARCHIPELAGO_TASK_COMPLETE`
- **Clarification protocol** — structured markers (`ARCHIPELAGO_NEED_CLARIFICATION`, `ARCHIPELAGO_NEED_PERMISSION`) that the adapter translates into typed protocol messages
- **Lessons-learned skill** — at task completion, Claude reviews its session and appends useful observations to `/workspace/.claude/lessons-learned.md`

### Protocol Messages

Communication between adapter and orchestrator uses typed JSON messages over WebSocket. See `docs/demo-archipelago/adapter_protocol_spec.md` for the full specification.

| Direction | Type | Purpose |
|-----------|------|---------|
| Orchestrator → Container | `InputMessage` | Deliver a prompt or answer |
| Orchestrator → Container | `ControlMessage` | Terminate, kill, resize |
| Container → Orchestrator | `OutputMessage` | Claude's text and tool use output |
| Container → Orchestrator | `StatusMessage` | Lifecycle: started, running, completed, exited |
| Container → Orchestrator | `InterruptMessage` | Clarification or permission request |

### Status Lifecycle

```
started → running → completed → exited
                  ↗
          (per turn: running while claude -p is active)
```

- `started`: container is up, adapter connected
- `running`: a `claude -p` invocation is active
- `completed`: Claude emitted `ARCHIPELAGO_TASK_COMPLETE` — task done, awaiting gate
- `exited`: container shutting down

### Container Environment

| Resource | Source |
|----------|--------|
| Git credentials | `GITHUB_TOKEN` → `.netrc` (written by entrypoint) |
| Git identity | `GIT_USER_NAME`, `GIT_USER_EMAIL` → `git config --global` (written by entrypoint) |
| Auth | `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` (exactly one required) |
| Workspace | Docker named volume mounted at `/workspace` |
| Repo | Cloned from `REPO_URL` at `REPO_REF` into `/workspace` by entrypoint |

## Cognitive Reasoning Research

The quality of autonomous work depends on the reasoning capabilities of the underlying model. We maintain an eval suite based on a taxonomy of 28 cognitive elements from "Cognitive Foundations for Reasoning and Their Manifestation in LLMs" (Kargupta et al., 2025), following Anthropic's agent eval methodology.

This research feeds back into the platform:

- **System instructions**: Findings about which cognitive elements models struggle with inform how we write CLAUDE.md and prompt construction across Agent Foundry
- **Model selection**: Eval scores guide which models are suitable for which types of autonomous work
- **Capability stack design**: Understanding model strengths and weaknesses shapes what we put in the capability stack to compensate or amplify
