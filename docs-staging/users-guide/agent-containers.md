# Agent Containers

Agent containers let you run AI agents inside Docker containers with defined instructions, tools, permissions, and a structured communication protocol. Agent Foundry provides the base infrastructure; your product defines what the agent does.

## Why containers?

An AI agent doing real work — writing code, analyzing documents, reviewing pull requests — needs an isolated environment. Containers provide:

- **Isolation**: the agent can't accidentally modify your host filesystem or interfere with other agents
- **Reproducibility**: every run starts from the same image with the same tools installed
- **Resource control**: memory limits, CPU quotas, PID limits prevent runaway processes
- **Security**: non-root user, dropped Linux capabilities, no access to host secrets unless explicitly forwarded

## How it works

There are three layers:

### 1. Base image

Agent Foundry ships a base Docker image (`acp-cc-worker`) that includes the Claude Code CLI, a WebSocket adapter, and a generic entrypoint. It handles authentication, git credentials, repo cloning, and adapter startup. You never modify this image directly.

Build it once:
```sh
pdm run docker-base
```

### 2. Product overlay

Your product layers on top of the base image to define what the agent does. This includes:

- **CLAUDE.md** — instructions the agent reads at startup ("you are a code reviewer", "use TDD", "output DONE when finished")
- **Marker config** — which stdout strings the agent uses to signal events (task complete, need clarification, need permission)
- **Skills** — reusable capabilities the agent can invoke during its session
- **Settings** — tool permissions and plugin configuration
- **Startup hook** — a shell script that runs at container start for product-specific setup (install plugins, check versions)

Build your product image:
```sh
pdm run docker-archipelago   # for Archipelago
```

### 3. Runtime configuration

When the orchestrator creates a container, it passes runtime configuration: which repo to clone, which WebSocket URL to connect to, resource constraints, and any extra environment variables. This is the per-task customization that varies across runs.

## The communication flow

```
Your orchestrator ←──WebSocket──→ Adapter (in container) ←──stdio──→ Claude Code
```

1. Your orchestrator starts a WebSocket server
2. The container starts and the adapter connects to your WebSocket URL
3. The adapter sends `status: started`
4. Your orchestrator sends a prompt via `InputMessage`
5. Claude Code runs, producing output that the adapter streams back as `OutputMessage`s
6. When Claude outputs a marker string (e.g., `MYPRODUCT_TASK_COMPLETE`), the adapter translates it into a structured `AgentEventMessage`
7. Your orchestrator handles the event (validate work, ask for clarification, terminate)

This is the **Agent Container Protocol (ACP)** — a small set of message types and event types that all agent containers use, regardless of which AI agent runs inside.

## Events the agent can signal

| Event | What it means | What you do |
|---|---|---|
| `task_complete` | Agent thinks the work is done | Run your gate check. Accept → terminate. Reject → send feedback and resume. |
| `clarification_requested` | Agent needs information | Read the question from the payload. Send an answer via `InputMessage`. |
| `permission_requested` | Agent wants to do something risky | Read the action and risk level. Approve or deny via `InputMessage`. |
| `stuck` | Agent can't proceed | Intervene — provide guidance or terminate. |

These events are defined by ACP. Your product defines the *marker strings* that trigger them — the mapping from "what Claude writes to stdout" to "which ACP event fires."

## Markers: connecting agent instructions to protocol events

This is the key mechanism that ties everything together:

1. Your **CLAUDE.md** tells the agent: "when you're done, output `MYPRODUCT_TASK_COMPLETE`"
2. Your **marker-config.json** tells the adapter: "when you see `MYPRODUCT_TASK_COMPLETE`, emit a `task_complete` event"
3. Your **orchestrator** receives the `task_complete` event and decides what to do

The agent never knows about ACP events. The orchestrator never sees raw marker strings. The adapter translates between the two worlds.

## Container lifecycle

```
create → start → [agent works, adapter communicates] → stop → destroy
```

The `ContainerManager` handles this. Key behaviors:

- **Volumes are preserved on destroy** — you can inspect the workspace after the container exits
- **Containers stay alive after task completion** — the gate check happens while the container is still running, so you can resume the same Claude session if the gate rejects
- **Multi-turn sessions** — the adapter supports `--resume` so Claude retains its full conversation context across multiple prompts

## Getting started

### Build images
```sh
pdm run docker-base          # base image (once)
pdm run docker-archipelago   # product overlay
```

### Run interactively (no orchestrator)
```sh
docker run -it \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -v myworkspace:/workspace \
  archipelago-cc-worker:latest
```

### Debug an exited container's workspace
```sh
./docker/bash-that-volume.sh <container_name_or_id>
```

### Run with an orchestrator
Pass `ACP_WS_URL` to connect the adapter to your WebSocket server:
```sh
docker run \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -e ACP_WS_URL="ws://host.docker.internal:8765/session-1" \
  -e REPO_URL="https://github.com/org/repo.git" \
  -v myworkspace:/workspace \
  myproduct-worker:latest
```

## Creating a new product

To define a new product that uses agent containers:

1. Write a **CLAUDE.md** — describe the agent's role, what markers to output, any domain-specific instructions
2. Write a **marker-config.json** — map your marker strings to ACP event types
3. Write a **Dockerfile** — `FROM acp-cc-worker:latest`, copy your files in
4. Optionally write a **product-init.sh** — for plugins, version checks, or environment setup
5. Optionally write **skills** — reusable capabilities the agent can invoke
6. Optionally override **settings.json** — to customize permissions or enable plugins

See `docker/` in this repo for the Archipelago reference implementation.

## Reference

For detailed schemas, message formats, field types, and the full ACP specification, see the [Agent Containers Guide for agents](../agents-guide/agent-containers-guide.md). That document is written as a machine-readable reference; this document explains the concepts behind it.

## Key files

| File | Purpose |
|---|---|
| `src/agent_foundry/acp/` | ACP module — protocol, adapters, container management |
| `src/agent_foundry/acp/docker/Dockerfile.base` | Base image definition |
| `src/agent_foundry/acp/docker/entrypoint.sh` | Base entrypoint |
| `docker/Dockerfile` | Archipelago product overlay |
| `docker/CLAUDE.md` | Archipelago agent instructions |
| `docker/marker-config.json` | Archipelago marker mappings |
| `docker/product-init.sh` | Archipelago startup hook |
| `docker/bash-that-volume.sh` | Debug utility — shell into a container's workspace |
