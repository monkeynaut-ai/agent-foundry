# Agent Container Reference

This reference describes the current Agent Foundry container execution path for
`AgentAction`.

## Current Scope

- Backend: Docker.
- Default executor: `agent_foundry.orchestration.container_executor.run_agent_in_container`.
- Agent harness: Claude Code CLI in headless structured-output mode.
- Output contract: `AgentTurnEnvelope[O]`, where `O` is the declared
  `AgentAction` output model.
- Container lifecycle owner: `AgentContainerRegistry` inside `run_process`.

This is an initial integration, not a universal agent-container abstraction.

## Key Types

| Type | Location | Purpose |
|------|----------|---------|
| `AgentAction[I, O]` | `agent_foundry.constructs` | Declares prompt, instructions, executor, model, reuse policy, access, and output type. |
| `ContainerReusePolicy` | `agent_foundry.constructs` | Controls whether a container/session is reused. |
| `ContainerConfig` | `agent_foundry.agents.lifecycle` | Resource and network constraints for container creation. |
| `ContainerManagerBase` | `agent_foundry.agents.lifecycle` | Backend seam for container lifecycle operations. |
| `AgentTurnEnvelope[O]` | `agent_foundry.agents.agent_turn_envelope` | Structured turn result wrapper. |
| `Responder` | `agent_foundry.responders` | Handles clarification and permission outcomes. |

## AgentAction Fields

Important fields:

- `name`: diagnostic label for artifacts, lifecycle events, and logs.
- `prompt_builder`: callable from input model to prompt text.
- `instructions_provider`: callable from input model to instruction text.
- `executor`: callable that performs the agent action.
- `reuse_policy`: explicit container/session reuse semantics.
- `model`: Claude model id for the current container executor.
- `gids`: supplementary group IDs for filesystem access.
- `mcp_servers`: MCP server allowlist for Claude Code tools.
- `container_config`: optional resource/network constraints.
- `timeout_seconds`: deadline for async executor paths.

## Executor Contract

The compiler calls `AgentAction.executor` with keyword arguments:

```python
executor(
    construct=agent_action,
    prompt=prompt,
    instructions=instructions,
    run_ctx=run_context,
)
```

The executor may be sync or async. It must return an instance of the declared
output model `O`; otherwise Agent Foundry raises a compilation/runtime boundary
error.

## Container Config Defaults

`ContainerConfig` defaults:

| Field | Default |
|-------|---------|
| `mem_limit_mb` | `2048` |
| `cpu_quota` | `100000` |
| `pids_limit` | `2048` |
| `tmp_size_mb` | `1024` |
| `network` | `NetworkMode.NONE` |

`network="host"` and `network="container:..."` are rejected because they dissolve
container isolation.

## Environment Forwarding

The default environment allowlist is intentionally small:

- `LANG`
- `TERM`
- `CLAUDE_CODE_OAUTH_TOKEN`
- `GIT_USER_NAME`
- `GIT_USER_EMAIL`

Additional environment must be passed explicitly through run/container wiring.

## Filesystem Access With GIDs

`AgentAction.gids` declares the supplementary Linux group IDs the agent process
should hold inside the container. This models access to resources rather than
agent identity:

- The in-container agent user remains stable.
- Directories can be owned by resource-specific groups.
- Directories with mode `775` grant write access to members of the owning group
  and read/execute access to other users.
- `gids=[]` is valid and means the agent receives no supplementary resource
  groups.
- An agent can hold more than one resource group, for example
  `gids=[1001, 1002]`.

The current implementation passes configured groups through
`SUPPLEMENTARY_GIDS` at container startup. The Docker entrypoint creates any
missing numeric groups, adds the agent user to those groups, then drops to the
non-root agent user before running commands.

A workspace can use nested group ownership to narrow write authority. For
example, `codebase/` can be owned by a codebase group while `codebase/tests/` is
owned by a test group. In that setup, an agent with only the codebase GID can
read `tests/` but cannot write there unless it also has the test GID. Bootstrap
ordering matters: assign parent directory ownership first, then override nested
directories.

## Turn Envelope

`AgentTurnEnvelope[O]` wraps one of:

- `success`: contains `payload: O`
- `clarification_needed`: contains a question and optional choices
- `permission_needed`: contains an action, risk level, and rationale
- `failed`: contains a reason and attempted approaches

The executor maps these outcomes to typed output, responder requests, or
agent/run failure behavior.
