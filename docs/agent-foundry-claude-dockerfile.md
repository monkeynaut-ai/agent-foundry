# Dockerfile Analysis: Gaps & Missing Capabilities

## What the Dockerfile currently provides

| Layer | What's there |
|---|---|
| **Base** | `python:3.13-slim` + git, curl, jq |
| **User** | Non-root `claude:1000` |
| **Claude Code** | Installed via `install.sh`, verified |
| **Config** | `settings.json` (tool permissions, sandbox), `claude.json` (onboarding bypass) |
| **Entrypoint** | Auth validation, version check, TTY detection, adapter mode |
| **Adapter** | `adapter.py` copied in |

## Holes & Missing Capabilities

### 1. No worker CLAUDE.md -- Critical

The adapter protocol spec (`docs/demo-archipelago/adapter_protocol_spec.md:3-22`) explicitly requires a CLAUDE.md with task completion protocol instructions. Without it:
- Claude Code won't emit `ARCHIPELAGO_TASK_COMPLETE` markers
- Inside-out completion detection fails entirely
- Every session requires external `control:complete` to proceed

The Dockerfile copies `settings.json` and `claude.json` but **no CLAUDE.md** at either `/home/claude/.claude/CLAUDE.md` (user-level) or meant to be in `/workspace/.claude/CLAUDE.md` (project-level). Our own notes at `docs/claude-dockerfile-notes.md:103` flag this: "No CLAUDE.md file present."

### 2. No sandbox dependencies

`docs/claude-dockerfile-notes.md:86-89` identifies that sandbox mode is broken inside the container because `bubblewrap`, `socat`, and `libseccomp-dev` are missing. The `settings.json` sets `"sandbox": {"enabled": true, "enableWeakerNestedSandbox": true}` but the actual dependencies aren't installed. This means sandbox is silently disabled at runtime -- the setting is a lie.

### 3. No `--max-turns` control

Claude Code supports `--max-turns` to cap agentic iterations. Neither the Dockerfile, entrypoint, nor the headless adapter pass this flag. A runaway Claude Code session will keep iterating until the container timeout kills it. The `_build_claude_cmd` in `lab/headless_adapter.py:58` doesn't include it. This is a safety gap -- `WorkerConstraints.timeout_seconds` is the only guard, but that's a blunt instrument compared to `--max-turns`.

### 4. No model selection

The handler and adapter never pass `--model` to Claude Code. It defaults to whatever Claude Code's default is (currently Opus 4.6). There's no way to:
- Use a cheaper model for simpler tasks
- Match the model to the task complexity
- Control costs at the container level

### 5. No `--system-prompt` / `--append-system-prompt` usage

Claude Code supports injecting system prompts via CLI flags. The current approach relies entirely on the prompt string built by `_build_prompt()` in `handler.py:110-126`. A system prompt could establish the worker role, constraints, and protocol without mixing them into the user prompt.

### 6. No `--allowedTools` / `--disallowedTools` at invocation time

The `settings.json` pre-allows `Bash, Read, Edit, Write, Glob, Grep` -- but these are static. The handler's `WorkerConstraints.allowed_commands` field exists in the model but is never wired to `--allowedTools`. Tasks that shouldn't have Bash access still get it.

### 7. No MCP server support

Claude Code supports MCP (Model Context Protocol) servers for extending capabilities. The Dockerfile installs zero MCP servers. No configuration in settings.json for `mcpServers`. This means Claude Code inside the container has no access to:
- External documentation search
- Database connectors
- Custom tool servers
- Any integration beyond its built-in tools

### 8. No hooks configuration

Claude Code supports pre/post tool execution hooks. These could be used to:
- Log tool usage for audit/observability
- Enforce additional constraints
- Capture cost/token metrics per tool call
- Block specific operations dynamically

None are configured.

### 9. No custom agents or skills baked in

`docs/claude-dockerfile-notes.md:93-97` notes "No custom agents" and "No skills installed." The directory structure supports `/home/claude/.claude/agents/` and `/home/claude/.claude/skills/`, but nothing is copied. The `/batch` skill (parallel worktree execution) was identified as "potentially very useful for Archipelago's parallel work pattern."

### 10. No cost/token tracking

Claude Code reports token usage in stream-json `result` events. The headless adapter in `_map_event_to_protocol` (`lab/headless_adapter.py:129-140`) extracts the `result` event but only captures `is_error` and `stop_reason` -- **not** `usage`, `cost`, or `tokens_used`. `WorkerResult` has no cost fields. `WorkerConstraints.max_cost_usd` exists but is never enforced.

### 11. No firewall/network security

Anthropic's official devcontainer includes `init-firewall.sh` with a default-deny outbound policy, whitelisting only npm, GitHub, Claude API, etc. The Archipelago Dockerfile has no network restrictions. `WorkerConstraints.network_policy` exists as a string field (default: `"none"`) but is never translated into actual Docker networking constraints in `create_container()`.

### 12. The adapter in the image is stale

The Dockerfile copies `adapter.py` into the image, but the headless adapter (`lab/headless_adapter.py`) is the evolved replacement. The `entrypoint.sh:34` still runs `python /home/claude/adapter.py` -- this may be the old PTY-based adapter, not the headless one.

### 13. No `--dangerously-skip-permissions` with proper containment

The devcontainer docs show that inside a properly firewalled container, `--dangerously-skip-permissions` is the recommended approach for unattended operation. The current setup uses `settings.json` permissions instead, which means Claude Code still shows permission prompts for tools not in the allow list (like `NotebookEdit`, `LSP`, `Agent`, etc.).

### 14. Memory limit is low

`WorkerConstraints.mem_limit_mb` defaults to 512MB. Claude Code (Node.js + TypeScript) alone consumes significant memory. Add Python for the adapter, git operations, and test runners -- 512MB is tight and likely causes OOM kills on real workloads.

---

## Improvement Recommendations

### Dockerfile Improvements

| Priority | Change | Impact |
|---|---|---|
| **P0** | Add a worker `CLAUDE.md` to `/home/claude/.claude/CLAUDE.md` | Enables task completion detection, establishes worker role |
| **P0** | Copy the headless adapter (not the stale `adapter.py`) | Uses the correct adapter code |
| **P1** | Install sandbox deps: `bubblewrap socat libseccomp-dev` | Makes `sandbox.enabled: true` actually work |
| **P1** | Add `init-firewall.sh` (model Anthropic's devcontainer) | Default-deny outbound, whitelist Claude API + GitHub only |
| **P1** | Raise default `mem_limit_mb` to at least 2048 | Prevents OOM on real workloads |
| **P2** | Create `/home/claude/.claude/agents/` and `/home/claude/.claude/skills/` directories with platform-level agents/skills | Extends CC's capabilities inside the container |
| **P2** | Add node.js dev tools (`npm`, `npx`) if workers need to run JS tests | Broader language support |

### Node/Handler Improvements

| Priority | Change | Impact |
|---|---|---|
| **P0** | Wire `--max-turns` from `WorkerConstraints` to the Claude CLI invocation | Prevents runaway sessions, finer than timeout |
| **P0** | Wire `--allowedTools` / `--disallowedTools` from `WorkerConstraints.allowed_commands` | Per-task tool restriction |
| **P1** | Pass `--model` based on task complexity or a new constraint field | Cost control, model matching |
| **P1** | Use `--append-system-prompt` to inject worker role/protocol instructions | Cleaner separation of system vs. user prompt |
| **P1** | Extract `usage`/cost from `result` events in the headless adapter and surface in `WorkerResult` | Cost tracking, enforce `max_cost_usd` |
| **P2** | Translate `network_policy` into actual Docker `--network` constraints in `create_container()` | Real network isolation |
| **P2** | Add hooks config to `settings.json` for observability (tool usage logging) | Audit trail, debugging |

### Container/Claude Code Process Improvements

| Priority | Change | Impact |
|---|---|---|
| **P0** | Use `--dangerously-skip-permissions` inside firewalled containers instead of `settings.json` allow lists | Eliminates permission prompts entirely, no trust prompt race |
| **P1** | Implement the two-layer CLAUDE.md strategy from our notes: bake platform defaults, clone project-specific from repo | Context-appropriate instructions per task |
| **P1** | Configure MCP servers in `settings.json` for common integrations (docs search, etc.) | Richer tool ecosystem inside container |
| **P2** | Add `--resume` support in the handler for multi-turn gate rejection recovery | Gate can reject and resume same session cleanly |
| **P2** | Surface `rate_limit_event` from stream-json for backpressure/throttling | Better handling of API limits |
| **P3** | Investigate `/batch` skill for parallel sub-task execution within a single container | Matches Archipelago's parallel work pattern |

### The biggest single win

Combining `--dangerously-skip-permissions` with a proper firewall (`init-firewall.sh`) would eliminate the entire trust prompt / permission prompt dance -- the trust confirmation thread (`_confirm_trust_and_prompt`), the `stty -icrnl` hack, the `\r` retry loop -- all of which exist only because Claude Code prompts for permissions in interactive mode. In headless mode with `--dangerously-skip-permissions`, none of that applies.

---

## Additional Missing Capabilities (from CLI research)

### High-impact flags not wired

| Flag | What it does | Current status |
|---|---|---|
| `--max-budget-usd <N>` | Hard stop when spend exceeds budget | Not used -- `WorkerConstraints.max_cost_usd` exists but is never enforced |
| `--fallback-model <model>` | Auto-switch when primary model is overloaded | Not used -- container just fails on rate limits |
| `--permission-prompt-tool <mcp_tool>` | Delegate permission decisions to an MCP tool programmatically | Not used -- would let the orchestrator handle permissions without breakpoints |
| `--append-system-prompt-file <path>` | Load system prompt additions from a file | Not used -- could load the worker CLAUDE.md content as system prompt |
| `--json-schema '<schema>'` | Validate output against JSON Schema | Not used -- could enforce structured progress output |
| `--add-dir <path>` | Add additional working directories | Not used -- could give CC access to shared resources |
| `--agents '<json>'` | Define custom subagents dynamically via JSON | Not used -- could inject Archipelago-specific agents at runtime |
| `--mcp-config <file>` | Load MCP servers from config | Not used |
| `--no-session-persistence` | Don't save sessions to disk | Should use -- container is ephemeral, no point persisting sessions |

### Settings.json features not configured

| Setting | Benefit |
|---|---|
| `hooks.PostToolUse` | Log every tool call for audit/observability |
| `hooks.Notification` | Forward Claude Code notifications to the orchestrator |
| `hooks.TaskCompleted` | Native task completion signal (vs. custom `ARCHIPELAGO_TASK_COMPLETE` marker) |
| `sandbox.network.allowedDomains` | Fine-grained network control within Claude Code's sandbox |
| `sandbox.filesystem.denyRead` | Prevent reading secrets even if sandbox is active |
| `effortLevel` | Control thinking depth per task -- cheaper for simple tasks |
| `mcpServers` config | Extend tool capabilities |
| `env.CLAUDE_CODE_EFFORT_LEVEL` | Cost optimization |
| `env.MAX_MCP_OUTPUT_TOKENS` | Control MCP verbosity |
| `outputStyle` | Could set to terse for container usage |

### Notable findings

**The `--permission-prompt-tool` flag is especially interesting** -- it lets you delegate permission decisions to an MCP tool. Instead of the current breakpoint/human-in-the-loop flow for permissions, the orchestrator could expose an MCP endpoint that programmatically approves or denies based on `WorkerConstraints`. This would replace a significant chunk of the interrupt handling code.

**The `TaskCompleted` hook event** is also notable -- Claude Code has a native task completion hook that could replace or supplement the custom `ARCHIPELAGO_TASK_COMPLETE` marker pattern. Worth investigating whether this fires reliably in headless mode.

---

## Appendix: Claude Code CLI Full Surface Area Reference

Research compiled from official Claude Code documentation.

### 1. CLI Flags & Options (All support `-p`/`--print` headless mode)

#### Core Execution Modes
- **`-p` / `--print`**: Run non-interactively, output result and exit
- **`-c` / `--continue`**: Resume most recent conversation in current directory
- **`-r <session>` / `--resume <session>`**: Resume specific session by ID or name
- **`--session-id <UUID>`**: Use specific session ID (must be valid UUID)
- **`--fork-session`**: Create new session ID instead of reusing original when resuming

#### Output Formatting & Control
- **`--output-format`**: `text` (default) | `json` | `stream-json`
- **`--json-schema '<schema>'`**: Get validated JSON matching JSON Schema (requires `--output-format json`)
- **`--verbose` / `--debug`**: Enable debug mode with optional category filtering (`api,hooks` or `!statsig,!file`)
- **`--include-partial-messages`**: Include partial streaming events (requires `--output-format stream-json`)
- **`--input-format`**: Specify input format (`text` | `stream-json`)

#### Model & Performance
- **`--model <alias|name>`**: Set model (`sonnet`, `opus`, `haiku`, `opusplan`, or full name like `claude-sonnet-4-6`)
- **`--fallback-model <model>`**: Automatic fallback when default model overloaded (print mode only)
- **`--max-turns <N>`**: Limit agentic turns (print mode only)
- **`--max-budget-usd <N>`**: Maximum spend before stopping (print mode only)
- **`--betas '<headers>'`**: Beta features via headers (API key users only)

#### System Prompt Customization
- **`--system-prompt '<text>'`**: Replace entire default prompt
- **`--system-prompt-file <path>`**: Load from file (replaces default)
- **`--append-system-prompt '<text>'`**: Append custom text to default prompt
- **`--append-system-prompt-file <path>`**: Append file contents to default prompt

#### Permissions & Security
- **`--permission-mode <mode>`**: `default` | `acceptEdits` | `plan` | `dontAsk` | `bypassPermissions`
- **`--dangerously-skip-permissions`**: Skip all permission prompts (use with caution)
- **`--allow-dangerously-skip-permissions`**: Enable bypass as option without activating immediately
- **`--permission-prompt-tool <mcp_tool>`**: Use MCP tool to handle permission prompts in non-interactive mode
- **`--allowedTools '<tool1>' '<tool2>'`**: Pre-approve tools (no prompts). Supports regex/glob patterns
- **`--disallowedTools '<tool1>' '<tool2>'`**: Remove tools from context (cannot be used)

#### Tool & MCP Configuration
- **`--tools '<list>'`**: Restrict which tools available (`"Bash,Edit,Read"` | `""` to disable all | `"default"` for all)
- **`--mcp-config <file|json>`**: Load MCP servers from JSON file/string (space-separated)
- **`--strict-mcp-config`**: Only use `--mcp-config` servers, ignore other configurations

#### Directory & File Access
- **`--add-dir <path>`**: Add additional working directories (validates paths exist)
- **`--settings <file|json>`**: Load additional settings from file or JSON string
- **`--setting-sources <list>`**: Comma-separated list (`user` | `project` | `local`)
- **`--plugin-dir <path>`**: Load plugins from directory (repeatable)

#### Custom Agents & Commands
- **`--agent <name>`**: Specify agent for session (overrides `agent` setting)
- **`--agents '<json>'`**: Define custom subagents dynamically via JSON
- **`--disable-slash-commands`**: Disable all skills and commands

#### Session Management
- **`--no-session-persistence`**: Disable session saving (print mode only)
- **`--from-pr <PR_number|URL>`**: Resume sessions linked to GitHub PR
- **`--remote '<description>'`**: Create new web session on claude.ai
- **`--teleport`**: Resume web session in local terminal

#### Chrome Integration
- **`--chrome`**: Enable Chrome browser integration
- **`--no-chrome`**: Disable Chrome integration

#### Worktrees & Isolation
- **`-w <name>` / `--worktree <name>`**: Start in isolated git worktree

#### IDE & Environment
- **`--ide`**: Auto-connect to IDE if exactly one available
- **`--init`**: Run initialization hooks and start interactive mode
- **`--init-only`**: Run initialization hooks and exit

#### Maintenance
- **`--maintenance`**: Run maintenance hooks and exit
- **`--version` / `-v`**: Output version number
- **`update`**: Update to latest version

---

### 2. Settings.json Configuration (All scopes: user/project/local)

#### Permissions
```json
{
  "permissions": {
    "allow": ["Bash(npm run *)", "Read", "Edit(/src/**)"],
    "ask": ["Bash(git push *)"],
    "deny": ["Bash(rm -rf *)"],
    "defaultMode": "acceptEdits|plan|dontAsk|bypassPermissions|default",
    "additionalDirectories": ["../docs/", "~/.config"],
    "disableBypassPermissionsMode": "disable"
  }
}
```

**Permission Syntax:**
- Tool names: `Bash`, `Read`, `Edit`, `WebFetch`, `Write`, `Glob`, `Grep`, `Agent(name)`, `mcp__server__tool`
- Bash patterns with `*` wildcards: `Bash(npm run *)`, `Bash(git * main)`
- File patterns (gitignore syntax): `Read(./.env)`, `Edit(/src/**)`, `Read(~/.zshrc)`, `Edit(//absolute/path)`
- Domain patterns: `WebFetch(domain:example.com)`
- MCP patterns: `mcp__github__*` (all GitHub tools), `mcp__github__search_repositories` (specific)

#### Sandbox Settings
```json
{
  "sandbox": {
    "enabled": true,
    "autoAllowBashIfSandboxed": true,
    "excludedCommands": ["docker", "git"],
    "allowUnsandboxedCommands": false,
    "filesystem": {
      "allowWrite": ["//tmp/build", "~/.kube"],
      "denyWrite": ["//etc"],
      "denyRead": ["~/.aws/credentials"]
    },
    "network": {
      "allowedDomains": ["github.com", "*.npmjs.org"],
      "allowUnixSockets": ["~/.ssh/agent-socket"],
      "allowAllUnixSockets": false,
      "allowLocalBinding": true,
      "allowManagedDomainsOnly": false,
      "httpProxyPort": 8080,
      "socksProxyPort": 8081
    },
    "enableWeakerNestedSandbox": false,
    "enableWeakerNetworkIsolation": false
  }
}
```

#### Environment Variables
```json
{
  "env": {
    "ENABLE_LSP_TOOL": "1",
    "DATABASE_URL": "postgres://...",
    "MAX_MCP_OUTPUT_TOKENS": "50000",
    "ENABLE_TOOL_SEARCH": "auto:5",
    "MCP_TIMEOUT": "10000",
    "CLAUDE_CODE_EFFORT_LEVEL": "high",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "32000"
  }
}
```

#### Model Configuration
```json
{
  "model": "sonnet|opus|haiku|opusplan|claude-opus-4-6",
  "availableModels": ["sonnet", "haiku"],
  "effortLevel": "low|medium|high"
}
```

#### MCP Server Configuration
```json
{
  "enableAllProjectMcpServers": true,
  "enabledMcpjsonServers": ["memory", "github"],
  "disabledMcpjsonServers": ["filesystem"],
  "allowedMcpServers": [{"serverName": "github"}],
  "deniedMcpServers": [{"serverName": "filesystem"}],
  "allowManagedMcpServersOnly": false
}
```

#### Hooks Configuration
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/validate.sh"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "npx prettier --write"
          }
        ]
      }
    ],
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "notify-send 'Claude Code' 'Needs attention'"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "compact",
        "hooks": [
          {
            "type": "command",
            "command": "echo 'Context restored after compaction'"
          }
        ]
      }
    ]
  },
  "disableAllHooks": false,
  "allowManagedHooksOnly": false,
  "allowedHttpHookUrls": ["https://hooks.example.com/*"],
  "httpHookAllowedEnvVars": ["MY_TOKEN"]
}
```

**Hook Events Available:**
- `SessionStart`, `SessionEnd`
- `UserPromptSubmit`, `Stop`
- `PreToolUse`, `PostToolUse`, `PostToolUseFailure`
- `PermissionRequest`, `Notification`
- `SubagentStart`, `SubagentStop`
- `TeammateIdle`, `TaskCompleted`
- `InstructionsLoaded`, `ConfigChange`
- `WorktreeCreate`, `WorktreeRemove`
- `PreCompact`

#### Plugin Configuration
```json
{
  "enabledPlugins": {
    "formatter@official": true,
    "deployer@official": false
  },
  "extraKnownMarketplaces": {
    "custom-tools": {
      "source": {"source": "github", "repo": "org/plugins"}
    }
  },
  "strictKnownMarketplaces": [],
  "blockedMarketplaces": []
}
```

#### Other Important Settings
```json
{
  "attribution": {
    "commit": "Generated with AI\n\nCo-Authored-By: AI <ai@example.com>",
    "pr": ""
  },
  "includeGitInstructions": true,
  "includeCoAuthoredBy": true,
  "respectGitignore": true,
  "outputStyle": "Explanatory",
  "showTurnDuration": true,
  "statusLine": {"type": "command", "command": "~/.claude/statusline.sh"},
  "fileSuggestion": {"type": "command", "command": "~/.claude/file-suggestion.sh"},
  "language": "english|japanese|spanish|...",
  "cleanupPeriodDays": 30,
  "plansDirectory": "./plans",
  "fastModePerSessionOptIn": true,
  "alwaysThinkingEnabled": true
}
```

#### Managed Settings (Admin-only)
```json
{
  "disableBypassPermissionsMode": "disable",
  "allowManagedPermissionRulesOnly": true,
  "allowManagedHooksOnly": true,
  "allowManagedMcpServersOnly": true,
  "allow_remote_sessions": false
}
```

---

### 3. MCP Server Capabilities

#### Installation Methods
```bash
# HTTP Server (recommended for remote)
claude mcp add --transport http github https://api.githubcopilot.com/mcp/

# SSE Server (deprecated, still supported)
claude mcp add --transport sse asana https://mcp.asana.com/sse

# Stdio Server (local processes)
claude mcp add --transport stdio db -- npx -y @bytebase/dbhub --dsn "postgresql://..."

# From JSON config
claude mcp add-json my-server '{"type":"http","url":"https://..."}'

# From Claude Desktop
claude mcp add-from-claude-desktop
```

#### OAuth Authentication
```bash
# Fixed callback port
claude mcp add --transport http --callback-port 8080 my-server https://...

# Pre-configured credentials
claude mcp add --transport http --client-id ID --client-secret --callback-port 8080 my-server https://...

# Within session
/mcp  # Interactive menu
```

#### Configuration Scopes
- **Local** (`~/.claude.json`): Personal per-project servers
- **Project** (`.mcp.json`): Team-shared servers (checked in)
- **User** (`~/.claude.json`): Cross-project personal servers
- **Managed** (`managed-mcp.json` system-wide): Admin-controlled

#### Configuration Features
- **Environment variable expansion**: `${VAR}` and `${VAR:-default}` in `.mcp.json`
- **Dynamic tool updates**: MCP servers can send `list_changed` notifications
- **Tool search**: Auto-enabled when tools exceed 10% of context
- **MCP prompts as commands**: `/mcp__server__prompt_name <args>`
- **Resource references**: `@server:protocol://resource/path`

#### Managed MCP Control Options
```json
{
  "managed-mcp.json": {
    "mcpServers": {
      "github": {"type": "http", "url": "https://api.githubcopilot.com/mcp/"}
    }
  },
  "allowedMcpServers": [
    {"serverName": "github"},
    {"serverCommand": ["npx", "-y", "approved-package"]},
    {"serverUrl": "https://mcp.company.com/*"}
  ],
  "deniedMcpServers": [
    {"serverName": "dangerous"}
  ]
}
```

---

### 4. Memory & Instruction Management

#### CLAUDE.md Project Instructions
- **Scope:** Loaded at session start, applies to project
- **Location:** Checked into repo at project root
- **Content:** Markdown with sections: coding style, testing practices, project-specific rules
- **Dynamic rules:** `.claude/rules/*.md` for path-specific patterns
- **Global CLAUDE.md:** `~/.claude/CLAUDE.md` applies to all projects
- **Lazy loading:** Files in `CLAUDE.md` via `!include` load on-demand
- **Auto-compact hints:** Custom compaction instructions via `# Compact instructions` section

#### Auto Memory
- **Location:** `~/.claude/projects/<project-hash>/memory/`
- **Disabled:** Set `ENABLE_MEMORY=false` to opt-out
- **View/edit:** `/memory` command in interactive mode
- **Contents:** Learned patterns, code conventions, session summaries

#### Context Management
- **Window:** 200K tokens baseline (1M for extended context with `sonnet[1m]`)
- **Auto-compaction:** Triggered when approaching limit (summarizes conversation)
- **Manual compaction:** `/compact <instructions>` with optional focus guidelines
- **Pre-compact hook:** `PreCompact` event for custom handling
- **Context display:** `/context` shows what's consuming space

---

### 5. Hooks System (Event-Driven Automation)

#### Hook Event Lifecycle
All hook types support exit codes:
- **Exit 0**: Allow action (or add context if applicable)
- **Exit 2**: Block action with stderr message
- **JSON output**: Structured decision control

#### Hook Types
1. **Command** (`type: "command"`): Shell script
2. **HTTP** (`type: "http"`): POST to webhook endpoint
3. **Prompt** (`type: "prompt"`): Single-turn LLM evaluation
4. **Agent** (`type: "agent"`): Multi-turn verification with tool access

#### Advanced Hook Features
- **Async hooks**: Run in background without blocking
- **Matchers**: Filter by tool name, notification type, config source, etc.
- **MCP tool hooks**: Support for MCP tools via `mcp__server__tool` matching
- **Structured output**: `hookSpecificOutput` JSON for granular control
- **Environment access**: `CLAUDE_PROJECT_DIR`, `CLAUDE_ENV_FILE` variables

#### Pre-configured Hook Locations
- `~/.claude/settings.json`: Global (all projects)
- `.claude/settings.json`: Project-level
- `.claude/settings.local.json`: Local (gitignored)
- Plugins: `plugin.json` or `/hooks/hooks.json`
- Skills/Agents: Frontmatter `[hooks]` section

---

### 6. Cost Tracking & Token Monitoring

#### Tracking Methods
- **Interactive:** `/cost` command (API users; subscribers use `/stats`)
- **Status line:** Custom script showing real-time usage
- **Environment:** `CLAUDE_CODE_MAX_OUTPUT_TOKENS`, `MAX_THINKING_TOKENS`
- **Workspace limits:** Set on Claude Console (API-based)

#### Cost-Control Flags
- `--max-turns <N>`: Stop after N agentic turns
- `--max-budget-usd <USD>`: Stop when budget exceeded
- Effort level: `CLAUDE_CODE_EFFORT_LEVEL=low|medium|high`

#### Cost Optimization
- **Prompt caching:** Automatic (disable with `DISABLE_PROMPT_CACHING=1`)
- **MCP tool search:** Auto-defers tools when >10% of context
- **Subagents:** Isolate verbose operations in separate context
- **Skills:** Pre-compute domain knowledge, load on-demand
- **Hooks:** Preprocess data before Claude sees it

---

### 7. Session Management (Persistence & Resumption)

#### Session Commands
```bash
# Resume by name/ID
claude --resume "session-name"

# Continue most recent
claude --continue

# Use specific session ID
claude --session-id "550e8400-e29b-41d4-a716-446655440000"

# Fork (create new from existing)
claude --resume abc123 --fork-session

# From PR
claude --from-pr 123
```

#### Session Features
- **Naming:** Sessions auto-get names; can be renamed with `/rename`
- **Cleanup:** Inactive sessions deleted after `cleanupPeriodDays` (default 30)
- **Persistence:** Stored by default; disable with `--no-session-persistence`
- **Context compaction:** Auto-triggered on context overflow
- **Checkpoint/rewind:** `/rewind` to restore to previous states

---

### 8. Skills & Custom Commands

#### Skill Structure
```yaml
# .claude/skills/my-skill.md
---
name: "my-skill"
trigger: "/my-skill"
description: "Does something useful"
tools: ["Read", "Bash"]  # Restrict tool access
arguments:
  - name: "target"
    description: "What to act on"
    required: true
---

# Skill implementation...
```

#### Skill Features
- **Frontmatter config:** Trigger, description, tool restrictions, arguments
- **Dynamic content:** String substitutions: `${PWD}`, `${ARGUMENT_NAME}`
- **Tool restriction:** Control which tools skill can access
- **Subagent delegation:** Run skill in isolated subagent context
- **Visibility control:** Restrict who can invoke via `permission` rules

---

### 9. Subagents (Delegation & Parallelization)

#### Built-in Subagents
- `Explore`: Research and investigation
- `Plan`: Architecture and design planning
- `Bash`: High-volume shell operations
- Custom agents defined in `.claude/agents/` or via `--agents` flag

#### Subagent Configuration
```json
{
  "tools": ["Read", "Bash"],
  "disallowedTools": ["WebFetch"],
  "model": "sonnet|opus|haiku|inherit",
  "skills": ["skill-name"],
  "mcpServers": ["github", "sentry"],
  "maxTurns": 10,
  "description": "When to invoke this agent"
}
```

#### Subagent Features
- **Parallel execution:** Multiple subagents run simultaneously
- **Isolated context:** Each has own context window
- **Cost isolation:** Verbose output stays in subagent context
- **Automatic delegation:** Based on description matching
- **Persistent memory:** Per-subagent memory can be enabled
- **Hook support:** Special `SubagentStart`, `SubagentStop` events

---

### 10. Docker & Container-Specific Guidance

#### Devcontainer Reference Setup
- **Location:** GitHub Anthropics repo `.devcontainer/` directory
- **Files:** `devcontainer.json`, `Dockerfile`, `init-firewall.sh`
- **Key features:**
  - Node.js 20 with dev dependencies
  - ZSH with productivity tools (fzf, git, etc.)
  - Firewall: Whitelisted domains (npm, GitHub, Claude API only)
  - VS Code integration: Pre-configured extensions
  - Session persistence: Shell history preserved

#### Container Best Practices
- **Headless mode:** Use `claude -p --output-format stream-json --verbose` for JSON streaming
- **Session resumption:** Capture `system.init` event for session ID, use `--resume SESSION_ID`
- **Task completion signals:**
  - **Inside-out:** Include instruction in worker CLAUDE.md to output `ARCHIPELAGO_TASK_COMPLETE` marker
  - **Outside-in:** Send `control: complete` message from orchestrator
- **Status lifecycle:** `started` -> `running` -> `turn_complete` (per turn) -> `completed` (task done, awaiting gate) -> `exited`
- **Permissions in containers:** Use `--dangerously-skip-permissions` (safe in isolated container)
- **MCP in containers:** Configure via `--mcp-config` flag or `.mcp.json`

#### Container Execution Patterns
```bash
# Headless with auto-approval and JSON output
claude -p \
  --output-format stream-json \
  --verbose \
  --allowedTools "Bash,Read,Edit" \
  --max-turns 10 \
  "Implement feature X"

# With custom system prompt
claude -p \
  --append-system-prompt-file /workspace/rules.txt \
  --system-prompt-file /workspace/custom-prompt.txt \
  "Analyze and fix issues"

# With MCP server config
claude -p \
  --mcp-config /workspace/mcp.json \
  --model opus \
  "Use database tools to migrate data"
```

---

### 11. Structured Outputs & Validation

#### JSON Schema Support
```bash
claude -p \
  --output-format json \
  --json-schema '{"type":"object","properties":{"functions":{"type":"array","items":{"type":"string"}}},"required":["functions"]}' \
  "Extract function names from auth.py"
```

#### Output Parsing with jq
```bash
# Extract text result
claude -p "Summarize" --output-format json | jq -r '.result'

# Extract structured output
claude -p "Extract data" --output-format json | jq '.structured_output'

# Stream tokens as they arrive
claude -p "Write poem" --output-format stream-json --verbose --include-partial-messages | \
  jq -rj 'select(.type == "stream_event" and .event.delta.type? == "text_delta") | .event.delta.text'
```
