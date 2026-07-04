# Agent Containers

Agent Foundry's initial `AgentAction` executor runs Claude Code inside a Docker
container. This is one adapter path, not the whole framework: applications can
provide different `AgentAction.executor` callables for SDK-backed agents,
service-backed agents, test doubles, or future harnesses.

Use containers when an agent needs an isolated workspace, filesystem access,
tools, and structured turn outcomes.

## What The Current Container Path Provides

- Docker-based process isolation.
- A non-root in-container user.
- Deny-by-default supplementary groups (`gids=[]`).
- Optional MCP server configuration.
- Explicit model and reuse-policy fields on `AgentAction`.
- Structured output through `AgentTurnEnvelope[OutputModel]`.
- Lifecycle events and artifacts for each run.

## Build The Images

Agent Foundry currently ships Dockerfiles under `src/agent_foundry/agents/docker/`.

```bash
pdm run docker-base
pdm run docker-foundry-dev
```

The base image contains the common runtime pieces. The foundry-dev image is the
current development image used by the repository.

## Authentication

Containerized Claude Code execution requires exactly one Claude/Anthropic auth
method to be available to the container:

```bash
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-..."
# or
export ANTHROPIC_API_KEY="sk-ant-..."
```

The current environment allowlist includes `CLAUDE_CODE_OAUTH_TOKEN` but does
not forward arbitrary host environment variables. Pass additional environment
through the runtime's explicit `extra_env` wiring when needed.

## Use An AgentAction

An `AgentAction` declares the typed input/output contract and the executor that
will fulfill it.

```python
from pydantic import BaseModel

from agent_foundry import AgentAction, ContainerReusePolicy
from agent_foundry.orchestration import run_agent_in_container


class ResearchInput(BaseModel):
    topic: str


class ResearchOutput(BaseModel):
    summary: str


researcher = AgentAction[ResearchInput, ResearchOutput](
    name="researcher",
    prompt_builder=lambda state: f"Research {state.topic}",
    instructions_provider=lambda _state: "Return a concise summary.",
    executor=run_agent_in_container,
    reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    model="claude-sonnet-4-6",
)
```

The executor must return an instance of the declared output model. The compiler
validates that boundary before merging the result back into process state.

## Authority And Access

Agent containers are safe-by-default where practical:

- `gids=[]` means no supplementary filesystem groups.
- `mcp_servers={}` means no MCP tool access.
- `ContainerConfig.network` defaults to `none`.
- Host environment forwarding is allowlisted.

Applications opt in to additional authority by setting fields on the
`AgentAction`, the run invocation, or the container config.

## Structured Turn Outcomes

The Claude Code container path expects each turn to produce an
`AgentTurnEnvelope[O]`, where `O` is the `AgentAction` output model.

The envelope can represent:

- success with a typed payload
- clarification needed
- permission needed
- failure

Clarification and permission outcomes route through the run's responder
provider. Success payloads are validated as the declared output model.

## Reuse Policy

`ContainerReusePolicy` is explicit because reuse changes semantics:

- `REUSE_RESUME`: reuse the same container and resume the agent session.
- `REUSE_NEW_SESSION`: reuse the container filesystem but start a fresh session.

## Reference

See [Agent container reference](../reference/agent-containers.md) for the current
model and protocol details.
