# Agent Containers Guide

Primary audience: autonomous systems and AI agents building on Agent Foundry.
Secondary audience: humans configuring, debugging, or extending agent containers.

---

## 1. Overview

### What agent containers do

An agent container runs an AI agent (Claude Code, Codex, or a custom agent) inside a Docker container with a defined set of instructions, tools, permissions, and communication protocols. The container communicates with an orchestrator over WebSocket using the Agent Container Protocol (ACP).

### When to use an agent container

Use an agent container when a task requires:
- An isolated execution environment (filesystem, network, resource limits)
- An AI agent that operates autonomously on a workspace (repository, document set, data)
- Bidirectional communication between the agent and an orchestration system
- Reproducible, configurable agent behavior across different products

Agent containers are not limited to code. They support any task an AI agent can perform: code analysis, test planning, document review, research synthesis, data analysis.

### Architecture

```
┌─────────────────────────────────────────────────┐
│ Docker Image                                    │
│                                                 │
│  Base Image (agent-worker)                     │
│  ├── Claude Code CLI                            │
│  ├── ACP adapter (claude_code.py)               │
│  ├── Generic entrypoint.sh                      │
│  └── Generic settings.json                      │
│                                                 │
│  Product Overlay                                │
│  ├── CLAUDE.md (agent instructions)             │
│  ├── marker-config.json (marker → event map)    │
│  ├── product-init.sh (startup hook)             │
│  ├── skills/                                    │
│  └── settings.json (overrides)                  │
│                                                 │
├─────────────────────────────────────────────────┤
│ At Runtime                                      │
│                                                 │
│  Entrypoint                                     │
│  ├── Auth validation                            │
│  ├── Git credentials + identity                 │
│  ├── Repo clone (if REPO_URL set)               │
│  ├── product-init.sh hook                       │
│  └── Adapter launch (if ACP_WS_URL set)         │
│                                                 │
│  Adapter                                        │
│  ├── Connects to orchestrator via WebSocket     │
│  ├── Runs agent turns (claude -p --resume)      │
│  ├── Matches stdout against marker mappings     │
│  └── Emits ACP protocol messages                │
│                                                 │
└──────────────────┬──────────────────────────────┘
                   │ WebSocket (ACP)
                   ▼
          ┌────────────────┐
          │  Orchestrator   │
          │  (product code) │
          └────────────────┘
```

---

## 2. Template: New Product Container

Copy and modify these files to define a new product that runs an AI agent in a container.

### Dockerfile

```dockerfile
FROM agent-worker:latest

# Product-specific tools (optional)
RUN pip install --no-cache-dir <your-tools>

# Agent instructions
COPY --chown=claude:claude CLAUDE.md /home/claude/.claude/CLAUDE.md

# Marker configuration
COPY --chown=claude:claude marker-config.json /home/claude/marker-config.json

# Settings overrides (optional)
COPY --chown=claude:claude settings.json /home/claude/.claude/settings.json

# Skills (optional)
COPY --chown=claude:claude skills/ /home/claude/.claude/skills/

# Startup hook (optional)
COPY --chown=claude:claude product-init.sh /home/claude/product-init.sh
RUN chmod +x /home/claude/product-init.sh

WORKDIR /workspace
```

### marker-config.json

```json
[
  {
    "pattern": "^MYPRODUCT_TASK_COMPLETE$",
    "event_type": "task_complete"
  },
  {
    "pattern": "^MYPRODUCT_NEED_CLARIFICATION\\s+(\\{.*\\})$",
    "event_type": "clarification_requested",
    "payload_group": 1
  },
  {
    "pattern": "^MYPRODUCT_NEED_PERMISSION\\s+(\\{.*\\})$",
    "event_type": "permission_requested",
    "payload_group": 1
  }
]
```

### CLAUDE.md

```markdown
# My Product Worker

You are Claude Code running inside a worker container. Your job is [describe the agent's role].

## Task completion

When your work is complete:
1. [product-specific completion steps]
2. Output the completion marker as the last line of your response:

\```
MYPRODUCT_TASK_COMPLETE
\```

## Asking for clarification

If you need information before proceeding, output on its own line:

\```
MYPRODUCT_NEED_CLARIFICATION {"question": "...", "options": [...], "blocking": true}
\```

## Asking for permission

If you need approval for a risky action, output on its own line:

\```
MYPRODUCT_NEED_PERMISSION {"action": "...", "risk_level": "low|medium|high", "why_needed": "..."}
\```
```

### product-init.sh (optional)

```sh
#!/bin/sh
# Runs inside the container at startup, after git setup, before adapter launch.
# Use for: plugin installation, version checks, environment setup.

# Example: install a Claude Code plugin
claude plugin marketplace add anthropics/claude-plugins-official
claude plugin install pyright-lsp@claude-plugins-official --scope user
```

### Build and run

```sh
# Build base image (once)
docker build -t agent-worker:latest -f src/agent_foundry/agents/docker/Dockerfile.base .

# Build product image
docker build -t myproduct-worker:latest -f path/to/Dockerfile .

# Run with orchestrator
docker run \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -e ACP_WS_URL="ws://host.docker.internal:8765/session-id" \
  -e REPO_URL="https://github.com/org/repo.git" \
  -e REPO_REF="main" \
  -v myworkspace:/workspace \
  myproduct-worker:latest

# Run interactively (no orchestrator)
docker run -it \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -v myworkspace:/workspace \
  myproduct-worker:latest
```

### Python orchestrator setup

```python
import docker
from agent_foundry.agents.container import ContainerManager, ContainerConfig

client = docker.from_env()
mgr = ContainerManager(
    client,
    default_image="myproduct-worker:latest",
    env_allowlist={"LANG", "TERM", "ANTHROPIC_API_KEY", "GITHUB_TOKEN"},
)

handle = mgr.create_container(
    workspace_volume="myworkspace",
    constraints=ContainerConfig(mem_limit_mb=2048),
    extra_env={
        "ACP_WS_URL": "ws://host.docker.internal:8765/session-1",
        "REPO_URL": "https://github.com/org/repo.git",
    },
)
mgr.start(handle)
```

---

## 3. Capability Stack

A capability stack defines the customizations applied to a container before the agent starts.

### Schema

```python
class CapabilityStack(BaseModel):
    claude_md: str | None = None
    skills: dict[str, str] = {}              # skill_name → SKILL.md content
    marker_mappings: list[MarkerMapping] = []
    settings: dict[str, Any] = {}            # Claude Code settings.json overrides
    plugins: list[str] = []                  # Plugin install commands
    env_allowlist_extra: set[str] = set()    # Additional env vars to forward
    extra_env: dict[str, str] = {}           # Static env vars to inject
```

Source: `agent_foundry.agents.capability_stack.CapabilityStack`

### Field reference

| Field | Type | Default | Purpose |
|---|---|---|---|
| `claude_md` | `str \| None` | `None` | CLAUDE.md content — the agent reads this as its instructions |
| `skills` | `dict[str, str]` | `{}` | Skill definitions keyed by name. Value is the SKILL.md content. |
| `marker_mappings` | `list[MarkerMapping]` | `[]` | Maps stdout markers to ACP event types. See [Section 5](#5-marker-mappings). |
| `settings` | `dict[str, Any]` | `{}` | Claude Code `settings.json` overrides (permissions, env, plugins) |
| `plugins` | `list[str]` | `[]` | Plugin install commands run at container start via product-init.sh |
| `env_allowlist_extra` | `set[str]` | `set()` | Additional host env vars to forward into the container |
| `extra_env` | `dict[str, str]` | `{}` | Static env vars injected into the container |

### CLAUDE.md content

The CLAUDE.md file is the primary mechanism for controlling agent behavior. The agent reads it on startup and follows its instructions throughout the session.

Required sections for ACP protocol compliance:
1. **Task completion** — instruct the agent to output the task-complete marker when done
2. **Clarification protocol** — instruct the agent to output the clarification marker when it needs information
3. **Permission protocol** — instruct the agent to output the permission marker when it needs approval

The marker strings in CLAUDE.md must match the patterns in `marker-config.json`. The CLAUDE.md tells the agent *what* to output; the marker config tells the adapter *what it means*.

### Skills

Skills are defined as `SKILL.md` files placed in `/home/claude/.claude/skills/<name>/SKILL.md`. Each skill provides the agent with a reusable capability it can invoke during its session.

### Plugins

Plugins extend Claude Code's tool capabilities (e.g., Pyright LSP for Python code navigation). Install plugins in `product-init.sh`:

```sh
claude plugin marketplace add <marketplace-name>
claude plugin install <plugin-name>@<marketplace-name> --scope user
```

Enable plugins in `settings.json`:

```json
{
  "enabledPlugins": {
    "pyright-lsp@claude-plugins-official": true
  }
}
```

### Settings and permissions

The base image provides a generic `settings.json` that allows common tools (`Bash`, `Read`, `Edit`, `Write`, `Glob`, `Grep`) and denies access to secrets (`.env`, `secrets/`). Products override by copying their own `settings.json`.

```json
{
  "permissions": {
    "allow": ["Bash", "Read", "Edit", "Write", "Glob", "Grep"],
    "deny": ["Read(./.env)", "Read(./.env.*)", "Read(./secrets/**)"]
  },
  "env": {
    "DISABLE_AUTOUPDATER": "1",
    "CLAUDE_CODE_TMPDIR": "/tmp",
    "ENABLE_LSP_TOOL": "1"
  }
}
```

---

## 4. Agent Container Protocol (ACP)

ACP is the event vocabulary and message schema for bidirectional communication between a containerized AI agent and its orchestrator. It is agent-agnostic and product-agnostic.

### Event vocabulary

#### Agent → Orchestrator events

| Event type | Trigger | Payload | Blocks session |
|---|---|---|---|
| `task_complete` | Agent considers work done | none | no — adapter stays alive for gate check |
| `clarification_requested` | Agent needs information to proceed | `{"question": str, "options": list, "default": str, "blocking": bool}` | yes |
| `permission_requested` | Agent needs approval for an action | `{"action": str, "risk_level": "low\|medium\|high", "why_needed": str, "alternatives": list}` | configurable by orchestrator |
| `stuck` | Agent cannot proceed | `{"reason": str}` | yes |
| `update_available` | Agent/tool version mismatch detected | `{"installed": str, "latest": str}` | no |

These events are delivered as `AgentEventMessage` instances. The `event_type` field contains the event name. The `payload` field contains the structured data. The `raw_line` field preserves the original stdout marker for audit.

#### Orchestrator → Agent messages

| Message type | Purpose | Key fields |
|---|---|---|
| `InputMessage` | Send text to the agent (answers, approvals, new instructions) | `text: str` |
| `ControlMessage` | Send commands to the adapter | `command: str, args: dict` |

Control commands:

| Command | Effect |
|---|---|
| `terminate` | Graceful shutdown |
| `kill` | Immediate shutdown |
| `complete` | Outside-in completion signal (orchestrator declares task done) |
| `resize` | Terminal resize. `args: {"rows": int, "cols": int}` |

### Message schemas

All messages are JSON objects with a `type` discriminator field. Parse with `parse_protocol_message(json_str)` from `agent_foundry.agents.protocol`.

#### OutputMessage (agent → orchestrator)

Streaming text output from the agent. Non-marker lines become OutputMessages.

```
{
  "type": "output",
  "session_id": "string",
  "text": "string",
  "stream": "stdout" | "stderr",   // default: "stdout"
  "timestamp": float                // Unix timestamp
}
```

#### AgentEventMessage (agent → orchestrator)

Structured event detected by marker matching. Replaces raw stdout markers with typed ACP events.

```
{
  "type": "agent_event",
  "session_id": "string",
  "event_type": "string",          // ACP event vocabulary
  "payload": {},                    // Parsed JSON from marker (or empty)
  "raw_line": "string",            // Original marker line
  "timestamp": float
}
```

#### StatusMessage (agent → orchestrator)

Lifecycle status transitions. Emitted by the adapter, not by markers.

```
{
  "type": "status",
  "session_id": "string",
  "status": "started" | "running" | "turn_complete" | "completed" | "exited" | "error",
  "exit_code": int | null,         // Present on terminal statuses
  "detail": "string",              // Human-readable context (e.g., stop_reason)
  "timestamp": float
}
```

#### InputMessage (orchestrator → agent)

```
{
  "type": "input",
  "session_id": "string",
  "text": "string"
}
```

#### ControlMessage (orchestrator → agent)

```
{
  "type": "control",
  "session_id": "string",
  "command": "resize" | "terminate" | "kill" | "complete",
  "args": {}                       // Command-specific. Default: empty.
}
```

### Status lifecycle

```
started ──→ running ──→ turn_complete ──→ completed ──→ exited
                    │                           ↑
                    │         (gate rejects → resume via InputMessage)
                    │
                    └──→ error
```

| Status | Meaning | What happens next |
|---|---|---|
| `started` | Adapter connected to WebSocket | Orchestrator sends first `InputMessage` or adapter runs initial prompt |
| `running` | A turn is in progress | Wait for `turn_complete` or `error` |
| `turn_complete` | One agent turn finished | Adapter stays alive. Orchestrator may send another `InputMessage` or `ControlMessage`. |
| `completed` | Agent signaled task done (via `task_complete` marker) or orchestrator sent `control: complete` | Container stays alive for gate check. Gate accepts → `control: terminate`. Gate rejects → `InputMessage` to resume. |
| `exited` | Container shutting down | Terminal state. |
| `error` | Unrecoverable failure (timeout, connection loss) | Terminal state. |

### Multi-turn sessions

The Claude Code adapter supports multi-turn sessions via `--resume`:

1. First turn: `claude -p "prompt" --output-format stream-json --verbose`
2. Adapter captures `session_id` from the `system.init` event in Claude's output
3. Subsequent turns: `claude -p "new prompt" --resume SESSION_ID --output-format stream-json --verbose`
4. This preserves Claude's full context across turns

**Gate-reject-and-resume flow:**
1. Agent outputs `task_complete` marker → adapter sends `status: completed`
2. Orchestrator's gate node validates the work
3. If gate rejects: orchestrator sends `InputMessage` with feedback → adapter runs another turn via `--resume`
4. If gate accepts: orchestrator sends `control: terminate` → adapter sends `status: exited` and shuts down

### Type aliases

```python
AdapterMessage = OutputMessage | AgentEventMessage | StatusMessage
OrchestratorMessage = InputMessage | ControlMessage
ProtocolMessage = AdapterMessage | OrchestratorMessage
```

### Backward compatibility

The Archipelago compatibility layer in `archipelago.docker_worker.protocol` converts old `"interrupt"` type messages to `"agent_event"`:

| Old field | New field |
|---|---|
| `type: "interrupt"` | `type: "agent_event"` |
| `interrupt_type: "clarification"` | `event_type: "clarification_requested"` |
| `interrupt_type: "permission"` | `event_type: "permission_requested"` |
| `interrupt_type: "update_available"` | `event_type: "update_available"` |

New products should use the `"agent_event"` format directly.

---

## 5. Marker Mappings

Marker mappings define how raw agent stdout is translated into ACP events.

### Schema

```python
class MarkerMapping(BaseModel):
    pattern: str                # Regex pattern to match against stdout lines
    event_type: str             # ACP event type to emit on match
    payload_group: int | None = None  # Regex group index containing JSON payload
```

Source: `agent_foundry.agents.protocol.MarkerMapping`

### How matching works

For each line of agent stdout, the adapter:

1. Strips whitespace from the line
2. Iterates compiled marker patterns **in order**
3. Tests each pattern with `re.match(pattern, line)`
4. On first match:
   - If `event_type` is `"task_complete"`: sets internal flag, does **not** emit the line as output
   - If `payload_group` is set: extracts `match.group(payload_group)` and JSON-parses it
   - If JSON parse fails: skips this marker, treats line as normal output
   - Otherwise: emits an `AgentEventMessage` with the `event_type` and parsed `payload`
   - Line is consumed — not emitted as `OutputMessage`
5. If no pattern matches: emits line as `OutputMessage`

### marker-config.json format

JSON array of objects. Each object maps to a `MarkerMapping`:

```json
[
  {
    "pattern": "^MYPRODUCT_TASK_COMPLETE$",
    "event_type": "task_complete"
  },
  {
    "pattern": "^MYPRODUCT_NEED_CLARIFICATION\\s+(\\{.*\\})$",
    "event_type": "clarification_requested",
    "payload_group": 1
  },
  {
    "pattern": "^MYPRODUCT_NEED_PERMISSION\\s+(\\{.*\\})$",
    "event_type": "permission_requested",
    "payload_group": 1
  }
]
```

The adapter loads this file at startup if it exists at `/home/claude/marker-config.json`.

### Rules for choosing marker strings

| Rule | Reason |
|---|---|
| Must appear on its own line | Adapter matches line-by-line |
| Must not appear in normal agent output | False positives cause protocol errors |
| Prefix with product name (e.g., `ARCHIPELAGO_`, `MYPRODUCT_`) | Avoids cross-product collisions |
| Use full-line anchors (`^...$`) | Prevents partial matches |
| Keep payload as valid JSON | Adapter JSON-parses the payload group |
| Document markers in CLAUDE.md | Agent needs to know what to output |

---

## 6. Container Lifecycle

### ContainerConfig

Resource constraints for a container. Products may pass their own constraint objects — the `create_container` method uses duck typing on `mem_limit_mb`, `cpu_quota`, and `pids_limit`.

```python
class ContainerConfig(BaseModel):
    mem_limit_mb: int = 2048       # Docker --memory (megabytes)
    cpu_quota: int = 100_000       # Docker --cpu-quota (microseconds per period)
    pids_limit: int = 256          # Docker --pids-limit
```

Source: `agent_foundry.agents.container.ContainerConfig`

### ContainerManager

Manages Docker container lifecycle with a safety baseline enforced on all containers.

```python
ContainerManager(
    client: docker.DockerClient,   # Docker SDK client
    default_image: str,            # Required. No default.
    env_allowlist: set[str] | None = None,  # Default: {LANG, TERM, ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN}
)
```

Source: `agent_foundry.agents.container.ContainerManager`

#### Methods

| Method | Signature | Returns | Notes |
|---|---|---|---|
| `create_container` | `(image?, workspace_volume?, constraints?, extra_env?)` | `ContainerHandle` | Enforces safety baseline. See below. |
| `start` | `(handle)` | `None` | Starts the container. |
| `stop` | `(handle, timeout=10)` | `None` | Graceful stop with timeout. |
| `destroy` | `(handle)` | `None` | Removes container. Preserves volumes (`v=False`). |
| `validate_image` | `(handle, required_commands=["claude"])` | `None` | Raises `ContainerCreationError` if any command missing. |
| `read_file_from_container` | `(handle, path)` | `str \| None` | Returns file content or `None` if not found. |
| `write_file_to_container` | `(handle, container_path, content)` | `None` | Writes via `put_archive`. |
| `copy_from_container` | `(handle, container_path, host_path)` | `bool` | Copies file to host. Returns `True` on success. |
| `cleanup_all` | `()` | `None` | Emergency cleanup of all tracked containers. |

### ContainerHandle

```python
@dataclass
class ContainerHandle:
    container_id: str
    status: str = "created"       # created → running → stopped → destroyed
    workspace_path: str = ""      # Default: /workspace
    created_at: float             # Unix timestamp
```

### Safety baseline

Every container created by `ContainerManager` enforces:

| Setting | Value | Reason |
|---|---|---|
| `user` | `"1000:1000"` | Non-root execution |
| `cap_drop` | `["ALL"]` | No Linux capabilities |
| `read_only` | `False` | Agent needs to write to workspace |
| `tmpfs` | `{"/tmp": "size=256m"}` | Ephemeral temp storage |
| `extra_hosts` | `{"host.docker.internal": "host-gateway"}` | Container-to-host networking for WebSocket |

### Environment variable forwarding

The generic allowlist forwards only auth-related variables:

```python
DEFAULT_ENV_ALLOWLIST = {"LANG", "TERM", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"}
```

Products extend the allowlist at `ContainerManager` construction or pass additional variables via `extra_env` on each `create_container` call.

```python
# Extend allowlist for all containers
mgr = ContainerManager(client, "img:1", env_allowlist={"LANG", "TERM", "ANTHROPIC_API_KEY", "GITHUB_TOKEN"})

# Or pass per-container
mgr.create_container(extra_env={"ACP_WS_URL": "ws://host.docker.internal:8765/s1"})
```

---

## 7. Adapters

An adapter is the in-container bridge between an AI agent CLI and the ACP WebSocket protocol.

### AdapterBase interface

```python
from agent_foundry.agents.adapter import AdapterBase, TurnResult

class AdapterBase(ABC):

    @abstractmethod
    def run_turn(
        self,
        prompt: str,
        ws: Any,                    # WebSocket connection
        protocol_session_id: str,
        **kwargs: Any,
    ) -> TurnResult:
        """Run a single agent turn. Send protocol messages via ws."""

    @abstractmethod
    def run(
        self,
        initial_prompt: str | None,
        ws_url: str,
        protocol_session_id: str,
        **kwargs: Any,
    ) -> int:
        """Run the full adapter loop. Returns exit code (0 = success)."""
```

### TurnResult

```python
@dataclass
class TurnResult:
    agent_session_id: str | None = None   # For --resume on next turn
    exit_code: int = -1                    # Agent CLI exit code
    task_complete: bool = False            # True if task_complete marker detected
```

### Claude Code adapter

The first adapter implementation. Runs `claude -p --output-format stream-json --verbose` and translates the structured JSON output into ACP messages.

```python
from agent_foundry.agents.adapters.claude_code import ClaudeCodeAdapter
from agent_foundry.agents.protocol import MarkerMapping

adapter = ClaudeCodeAdapter(
    marker_mappings=[
        MarkerMapping(pattern=r"^DONE$", event_type="task_complete"),
    ],
    skip_permissions=False,         # --dangerously-skip-permissions
    turn_timeout=600.0,             # Seconds per turn
    connect_timeout=30.0,           # WebSocket connect timeout
)
```

Source: `agent_foundry.agents.adapters.claude_code.ClaudeCodeAdapter`

#### Claude Code stream-json event mapping

| Claude event type | ACP output |
|---|---|
| `assistant` (text content) | `OutputMessage` per text block. Marker lines → `AgentEventMessage`. |
| `assistant` (tool_use content) | `OutputMessage` with `[tool_use: name] summary` |
| `result` | `StatusMessage` with `status: "turn_complete"` |
| `error` | `OutputMessage` on `stderr` stream |
| `system` (subtype: init) | Session ID captured for `--resume`. No protocol message emitted. |
| `tool_result` | Ignored (tool results are internal to the agent) |
| `rate_limit_event` | Ignored |

#### CLI usage

The adapter can run as a standalone script inside the container:

```
python adapter.py --protocol WS_URL [OPTIONS] [PROMPT]

Options:
  --protocol WS_URL         WebSocket URL (default: ws://localhost:8765)
  --session-id ID           Protocol session ID (default: "default")
  --timeout SECS            Seconds per turn (default: 600)
  --dangerously-skip-permissions  Pass to claude CLI
  --marker-config FILE      Path to JSON marker mappings file
  --verbose                 Debug logging
```

If `PROMPT` is omitted, the adapter waits for the first `InputMessage` before running any turn.

### Writing a new adapter

To support a non-Claude-Code agent:

1. Create `agent_foundry/agents/adapters/your_agent.py`
2. Subclass `AdapterBase`
3. Implement `run_turn()`:
   - Launch the agent CLI with the prompt
   - Read stdout line by line
   - Match lines against `marker_mappings` (use `MarkerMapping` and compile patterns)
   - Send `AgentEventMessage` for matches, `OutputMessage` for non-matches
   - Send `StatusMessage(status="turn_complete")` when the turn ends
   - Return `TurnResult` with session ID, exit code, completion flag
4. Implement `run()`:
   - Connect to WebSocket
   - Send `StatusMessage(status="started")`
   - Run initial turn if prompt provided
   - Listen for `InputMessage` and `ControlMessage`
   - Send `StatusMessage(status="completed")` on task completion
   - Send final `StatusMessage(status="exited")` on shutdown

---

## 8. Docker Images

### Base image: agent-worker

Build from project root:

```sh
docker build -t agent-worker:latest -f src/agent_foundry/agents/docker/Dockerfile.base .
```

Contents:

| Layer | What it provides |
|---|---|
| `python:3.13` | Python runtime, pip |
| System packages | `git`, `curl`, `jq` |
| Non-root user | `claude` (1000:1000) |
| Claude Code CLI | `/home/claude/.local/bin/claude` |
| `websockets` | Python WebSocket library for the adapter |
| ACP adapter | `/home/claude/adapter.py` |
| Settings | `/home/claude/.claude/settings.json` (generic) |
| Onboarding skip | `/home/claude/.claude.json` |
| Entrypoint | `/home/claude/entrypoint.sh` |

### Entrypoint behavior

Executed as PID 1 when the container starts.

```
1. Auth validation
   ├── Both CLAUDE_CODE_OAUTH_TOKEN and ANTHROPIC_API_KEY set → error, exit 1
   └── Neither set → error, exit 1

2. Git credentials
   └── If GITHUB_TOKEN set → write to /home/claude/.netrc

3. Git identity
   ├── If GIT_USER_NAME set → git config --global user.name
   └── If GIT_USER_EMAIL set → git config --global user.email

4. Repo clone
   └── If REPO_URL set and /workspace/.git absent → git clone

5. Product init hook
   └── If /home/claude/product-init.sh exists → source it

6. Adapter launch (if ACP_WS_URL or ARCHIPELAGO_WS_URL set)
   ├── Read ACP_TURN_TIMEOUT (default: 3600)
   ├── Read ACP_SKIP_PERMISSIONS (default: "0")
   ├── If /home/claude/marker-config.json exists → pass --marker-config
   └── exec python adapter.py --protocol $WS_URL ...

7. Fallback (no WS URL)
   ├── TTY attached → exec claude "$@" (interactive)
   └── No TTY → exec claude -p "$@" (headless)
```

### Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | one of two | — | Authentication (subscription billing) |
| `ANTHROPIC_API_KEY` | one of two | — | Authentication (API billing) |
| `GITHUB_TOKEN` | no | — | Written to `.netrc` for git credential auth |
| `GIT_USER_NAME` | no | — | `git config --global user.name` |
| `GIT_USER_EMAIL` | no | — | `git config --global user.email` |
| `REPO_URL` | no | — | Repository to clone into `/workspace` |
| `REPO_REF` | no | `main` | Branch to clone |
| `ACP_WS_URL` | no | — | WebSocket URL for adapter connection |
| `ACP_TURN_TIMEOUT` | no | `3600` | Seconds per agent turn |
| `ACP_SKIP_PERMISSIONS` | no | `0` | Set to `"1"` to pass `--dangerously-skip-permissions` |
| `ARCHIPELAGO_WS_URL` | no | — | Backward compat alias for `ACP_WS_URL` |
| `ARCHIPELAGO_TURN_TIMEOUT` | no | — | Backward compat alias for `ACP_TURN_TIMEOUT` |
| `ARCHIPELAGO_SKIP_PERMISSIONS` | no | — | Backward compat alias for `ACP_SKIP_PERMISSIONS` |

### Product overlay pattern

Products layer on the base image:

```dockerfile
FROM agent-worker:latest

# Product-specific tools
RUN pip install --no-cache-dir pyright && pyright --version

# Override settings (adds plugin config, custom permissions)
COPY --chown=claude:claude settings.json /home/claude/.claude/settings.json

# Agent instructions
COPY --chown=claude:claude CLAUDE.md /home/claude/.claude/CLAUDE.md

# Marker mappings
COPY --chown=claude:claude marker-config.json /home/claude/marker-config.json

# Skills
COPY --chown=claude:claude skills/ /home/claude/.claude/skills/

# Startup hook
COPY --chown=claude:claude product-init.sh /home/claude/product-init.sh
RUN chmod +x /home/claude/product-init.sh

WORKDIR /workspace
```

### product-init.sh hook

Sourced (not executed) by the base entrypoint after git setup, before adapter launch. Runs in the same shell — can set environment variables, install plugins, perform checks.

Do not use `exec` in product-init.sh — it would replace the entrypoint process.

---

## 9. Workspace and Recovery

### Workspace volumes

Agent containers mount a Docker named volume at `/workspace`. This volume:
- Persists across container restarts (crash recovery)
- Can be shared between containers (multi-node workflows)
- Is **not** removed by `ContainerManager.destroy()` (`v=False`)

The entrypoint clones a repo into `/workspace` on first run. If `/workspace/.git` already exists (shared volume, restart), the clone is skipped.

### WorkspaceSnapshot

Captures git state for crash recovery or checkpoint.

```python
class WorkspaceSnapshot(BaseModel):
    commit_sha: str                # HEAD commit SHA
    working_tree_diff: str         # Output of git diff
    transcript_path: str | None    # Path to copied transcript file
```

Source: `agent_foundry.agents.recovery.WorkspaceSnapshot`

### capture_workspace_state()

```python
from agent_foundry.agents.recovery import capture_workspace_state

# Host mode — workspace is a local directory
snapshot = capture_workspace_state(
    output_path=Path("/tmp/recovery"),
    workspace_path=Path("/workspace"),
)

# Container mode — workspace is inside a running container
snapshot = capture_workspace_state(
    output_path=Path("/tmp/recovery"),
    container_mgr=mgr,
    container_handle=handle,
)
```

| Parameter | Type | Required | Purpose |
|---|---|---|---|
| `output_path` | `Path` | yes | Directory to write snapshot artifacts |
| `workspace_path` | `Path` | host mode | Local workspace directory |
| `git_runner` | `callable` | no | Custom git command runner (host mode) |
| `container_mgr` | `ContainerManager` | container mode | For container-based file I/O |
| `container_handle` | `ContainerHandle` | container mode | Target container |

Host mode uses `subprocess.check_output` for git commands. Container mode uses `container_handle._container.exec_run`.

### Adding product-specific recovery data

`WorkspaceSnapshot` captures only git state. Products compose with domain-specific data:

```python
from agent_foundry.agents.recovery import WorkspaceSnapshot, capture_workspace_state

class MyProductSnapshot(BaseModel):
    base: WorkspaceSnapshot
    progress_events: list[MyProgressEvent]
    custom_data: dict

base_snapshot = capture_workspace_state(output_path=output, container_mgr=mgr, container_handle=handle)
product_snapshot = MyProductSnapshot(
    base=base_snapshot,
    progress_events=parse_my_progress(output),
    custom_data={...},
)
```

---

## 10. Error Types

All errors are in `agent_foundry.agents.errors`.

| Error | Raised when | Context fields | Catch when |
|---|---|---|---|
| `ContainerCreationError` | `create_container()` fails (Docker daemon down, image not found, resource limits exceeded) | `image: str \| None` | Creating containers |
| `ContainerLifecycleError` | `start()`, `stop()`, or `destroy()` fails | `container_id: str \| None` | Managing container lifecycle |
| `SessionError` | PTY session operation fails (exec_create, send_input) | `container_id: str \| None` | PTY session management |
| `AdapterError` | Adapter connection fails, parsing error in adapter logic | — | Adapter operations |
| `ProtocolError` | `parse_protocol_message()` receives invalid JSON, missing `type`, or unknown message type | — | Parsing WebSocket messages |

All errors are subclasses of `Exception`.

---

## 11. Examples

### Archipelago: autonomous software development

Reference implementation in `src/archipelago/` and `docker/`.

**Capability stack:**
- CLAUDE.md: TDD methodology, software design principles, LSP-first navigation, task completion protocol
- 4 marker mappings: `ARCHIPELAGO_TASK_COMPLETE`, `ARCHIPELAGO_NEED_CLARIFICATION`, `ARCHIPELAGO_NEED_PERMISSION`, `ARCHIPELAGO_UPDATE_AVAILABLE`
- Pyright LSP plugin installed via product-init.sh
- Lessons-learned skill invoked before task completion
- Extended env allowlist: `GITHUB_TOKEN`, `GIT_USER_NAME`, `GIT_USER_EMAIL`, `ARCHIPELAGO_WS_URL`

**Container configuration:**
```python
from archipelago.docker_worker.container import create_archipelago_container_manager

mgr = create_archipelago_container_manager(docker.from_env())
handle = mgr.create_container(
    workspace_volume=f"archipelago-{session_id}",
    constraints=worker_input.constraints,
    extra_env={
        "ARCHIPELAGO_WS_URL": ws_url,
        "REPO_URL": worker_input.repo_url,
    },
)
```

**Files:**
- `docker/Dockerfile` — product overlay on `agent-worker:latest`
- `docker/CLAUDE.md` — agent instructions
- `docker/marker-config.json` — marker mappings
- `docker/product-init.sh` — Pyright plugin install, version check
- `docker/settings.json` — permissions with Pyright plugin enabled
- `docker/skills/lessons-learned/SKILL.md` — session-end reflection skill

### Minimal: code review agent

A read-only agent that reviews code and reports findings. No repo modification, single-turn.

**marker-config.json:**
```json
[
  {"pattern": "^REVIEW_COMPLETE$", "event_type": "task_complete"}
]
```

**CLAUDE.md:**
```markdown
# Code Review Agent

Review the code in /workspace and report findings. Do not modify any files.

When your review is complete, output:
\```
REVIEW_COMPLETE
\```
```

**settings.json:**
```json
{
  "permissions": {
    "allow": ["Read", "Glob", "Grep"],
    "deny": ["Bash", "Edit", "Write"]
  }
}
```

**Orchestrator:**
```python
mgr = ContainerManager(client, default_image="review-agent:latest")
handle = mgr.create_container(
    constraints=ContainerConfig(mem_limit_mb=512),
    extra_env={"ACP_WS_URL": ws_url, "REPO_URL": repo_url},
)
mgr.start(handle)
# Listen for OutputMessages (review findings) and task_complete event
```

### Minimal: document analysis agent

Analyzes documents injected into the container. No repo clone, no git.

**marker-config.json:**
```json
[
  {"pattern": "^ANALYSIS_DONE$", "event_type": "task_complete"},
  {"pattern": "^NEED_INFO\\s+(\\{.*\\})$", "event_type": "clarification_requested", "payload_group": 1}
]
```

**Orchestrator:**
```python
mgr = ContainerManager(client, default_image="doc-analyzer:latest")
handle = mgr.create_container(
    constraints=ContainerConfig(mem_limit_mb=1024),
    extra_env={"ACP_WS_URL": ws_url},
)
mgr.start(handle)

# Inject documents (no repo clone)
mgr.write_file_to_container(handle, "/workspace/report.pdf", pdf_content)
mgr.write_file_to_container(handle, "/workspace/data.csv", csv_content)

# Send analysis prompt via InputMessage over WebSocket
```
