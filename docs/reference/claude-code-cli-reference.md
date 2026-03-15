# Claude Code CLI Full Surface Area Reference

Research compiled from official Claude Code documentation.

> **Note**: This is a locally maintained reference. The official Claude Code documentation at [code.claude.com/docs](https://code.claude.com/docs) is the canonical source of truth and may be more current.

## 1. CLI Flags & Options (All support `-p`/`--print` headless mode)

### Core Execution Modes
- **`-p` / `--print`**: Run non-interactively, output result and exit
- **`-c` / `--continue`**: Resume most recent conversation in current directory
- **`-r <session>` / `--resume <session>`**: Resume specific session by ID or name
- **`--session-id <UUID>`**: Use specific session ID (must be valid UUID)
- **`--fork-session`**: Create new session ID instead of reusing original when resuming

### Output Formatting & Control
- **`--output-format`**: `text` (default) | `json` | `stream-json`
- **`--json-schema '<schema>'`**: Get validated JSON matching JSON Schema (requires `--output-format json`)
- **`--verbose` / `--debug`**: Enable debug mode with optional category filtering (`api,hooks` or `!statsig,!file`)
- **`--include-partial-messages`**: Include partial streaming events (requires `--output-format stream-json`)
- **`--input-format`**: Specify input format (`text` | `stream-json`)

### Model & Performance
- **`--model <alias|name>`**: Set model (`sonnet`, `opus`, `haiku`, `opusplan`, or full name like `claude-sonnet-4-6`)
- **`--fallback-model <model>`**: Automatic fallback when default model overloaded (print mode only)
- **`--max-turns <N>`**: Limit agentic turns (print mode only)
- **`--max-budget-usd <N>`**: Maximum spend before stopping (print mode only)
- **`--betas '<headers>'`**: Beta features via headers (API key users only)

### System Prompt Customization
- **`--system-prompt '<text>'`**: Replace entire default prompt
- **`--system-prompt-file <path>`**: Load from file (replaces default)
- **`--append-system-prompt '<text>'`**: Append custom text to default prompt
- **`--append-system-prompt-file <path>`**: Append file contents to default prompt

### Permissions & Security
- **`--permission-mode <mode>`**: `default` | `acceptEdits` | `plan` | `dontAsk` | `bypassPermissions`
- **`--dangerously-skip-permissions`**: Skip all permission prompts (use with caution)
- **`--allow-dangerously-skip-permissions`**: Enable bypass as option without activating immediately
- **`--permission-prompt-tool <mcp_tool>`**: Use MCP tool to handle permission prompts in non-interactive mode
- **`--allowedTools '<tool1>' '<tool2>'`**: Pre-approve tools (no prompts). Supports regex/glob patterns
- **`--disallowedTools '<tool1>' '<tool2>'`**: Remove tools from context (cannot be used)

### Tool & MCP Configuration
- **`--tools '<list>'`**: Restrict which tools available (`"Bash,Edit,Read"` | `""` to disable all | `"default"` for all)
- **`--mcp-config <file|json>`**: Load MCP servers from JSON file/string (space-separated)
- **`--strict-mcp-config`**: Only use `--mcp-config` servers, ignore other configurations

### Directory & File Access
- **`--add-dir <path>`**: Add additional working directories (validates paths exist)
- **`--settings <file|json>`**: Load additional settings from file or JSON string
- **`--setting-sources <list>`**: Comma-separated list (`user` | `project` | `local`)
- **`--plugin-dir <path>`**: Load plugins from directory (repeatable)

### Custom Agents & Commands
- **`--agent <name>`**: Specify agent for session (overrides `agent` setting)
- **`--agents '<json>'`**: Define custom subagents dynamically via JSON
- **`--disable-slash-commands`**: Disable all skills and commands

### Session Management
- **`--no-session-persistence`**: Disable session saving (print mode only)
- **`--from-pr <PR_number|URL>`**: Resume sessions linked to GitHub PR
- **`--remote '<description>'`**: Create new web session on claude.ai
- **`--teleport`**: Resume web session in local terminal

### Chrome Integration
- **`--chrome`**: Enable Chrome browser integration
- **`--no-chrome`**: Disable Chrome integration

### Worktrees & Isolation
- **`-w <name>` / `--worktree <name>`**: Start in isolated git worktree

### IDE & Environment
- **`--ide`**: Auto-connect to IDE if exactly one available
- **`--init`**: Run initialization hooks and start interactive mode
- **`--init-only`**: Run initialization hooks and exit

### Maintenance
- **`--maintenance`**: Run maintenance hooks and exit
- **`--version` / `-v`**: Output version number
- **`update`**: Update to latest version

---

## 2. Settings.json Configuration (All scopes: user/project/local)

### Permissions
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

### Sandbox Settings
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

### Environment Variables
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

### Model Configuration
```json
{
  "model": "sonnet|opus|haiku|opusplan|claude-opus-4-6",
  "availableModels": ["sonnet", "haiku"],
  "effortLevel": "low|medium|high"
}
```

### MCP Server Configuration
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

### Hooks Configuration
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

### Plugin Configuration
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

### Other Important Settings
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

### Managed Settings (Admin-only)
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

## 3. MCP Server Capabilities

### Installation Methods
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

### OAuth Authentication
```bash
# Fixed callback port
claude mcp add --transport http --callback-port 8080 my-server https://...

# Pre-configured credentials
claude mcp add --transport http --client-id ID --client-secret --callback-port 8080 my-server https://...

# Within session
/mcp  # Interactive menu
```

### Configuration Scopes
- **Local** (`~/.claude.json`): Personal per-project servers
- **Project** (`.mcp.json`): Team-shared servers (checked in)
- **User** (`~/.claude.json`): Cross-project personal servers
- **Managed** (`managed-mcp.json` system-wide): Admin-controlled

### Configuration Features
- **Environment variable expansion**: `${VAR}` and `${VAR:-default}` in `.mcp.json`
- **Dynamic tool updates**: MCP servers can send `list_changed` notifications
- **Tool search**: Auto-enabled when tools exceed 10% of context
- **MCP prompts as commands**: `/mcp__server__prompt_name <args>`
- **Resource references**: `@server:protocol://resource/path`

### Managed MCP Control Options
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

## 4. Memory & Instruction Management

### CLAUDE.md Project Instructions
- **Scope:** Loaded at session start, applies to project
- **Location:** Checked into repo at project root
- **Content:** Markdown with sections: coding style, testing practices, project-specific rules
- **Dynamic rules:** `.claude/rules/*.md` for path-specific patterns
- **Global CLAUDE.md:** `~/.claude/CLAUDE.md` applies to all projects
- **Lazy loading:** Files in `CLAUDE.md` via `!include` load on-demand
- **Auto-compact hints:** Custom compaction instructions via `# Compact instructions` section

### Auto Memory
- **Location:** `~/.claude/projects/<project-hash>/memory/`
- **Disabled:** Set `ENABLE_MEMORY=false` to opt-out
- **View/edit:** `/memory` command in interactive mode
- **Contents:** Learned patterns, code conventions, session summaries

### Context Management
- **Window:** 200K tokens baseline (1M for extended context with `sonnet[1m]`)
- **Auto-compaction:** Triggered when approaching limit (summarizes conversation)
- **Manual compaction:** `/compact <instructions>` with optional focus guidelines
- **Pre-compact hook:** `PreCompact` event for custom handling
- **Context display:** `/context` shows what's consuming space

---

## 5. Hooks System (Event-Driven Automation)

### Hook Event Lifecycle
All hook types support exit codes:
- **Exit 0**: Allow action (or add context if applicable)
- **Exit 2**: Block action with stderr message
- **JSON output**: Structured decision control

### Hook Types
1. **Command** (`type: "command"`): Shell script
2. **HTTP** (`type: "http"`): POST to webhook endpoint
3. **Prompt** (`type: "prompt"`): Single-turn LLM evaluation
4. **Agent** (`type: "agent"`): Multi-turn verification with tool access

### Advanced Hook Features
- **Async hooks**: Run in background without blocking
- **Matchers**: Filter by tool name, notification type, config source, etc.
- **MCP tool hooks**: Support for MCP tools via `mcp__server__tool` matching
- **Structured output**: `hookSpecificOutput` JSON for granular control
- **Environment access**: `CLAUDE_PROJECT_DIR`, `CLAUDE_ENV_FILE` variables

### Pre-configured Hook Locations
- `~/.claude/settings.json`: Global (all projects)
- `.claude/settings.json`: Project-level
- `.claude/settings.local.json`: Local (gitignored)
- Plugins: `plugin.json` or `/hooks/hooks.json`
- Skills/Agents: Frontmatter `[hooks]` section

---

## 6. Cost Tracking & Token Monitoring

### Tracking Methods
- **Interactive:** `/cost` command (API users; subscribers use `/stats`)
- **Status line:** Custom script showing real-time usage
- **Environment:** `CLAUDE_CODE_MAX_OUTPUT_TOKENS`, `MAX_THINKING_TOKENS`
- **Workspace limits:** Set on Claude Console (API-based)

### Cost-Control Flags
- `--max-turns <N>`: Stop after N agentic turns
- `--max-budget-usd <USD>`: Stop when budget exceeded
- Effort level: `CLAUDE_CODE_EFFORT_LEVEL=low|medium|high`

### Cost Optimization
- **Prompt caching:** Automatic (disable with `DISABLE_PROMPT_CACHING=1`)
- **MCP tool search:** Auto-defers tools when >10% of context
- **Subagents:** Isolate verbose operations in separate context
- **Skills:** Pre-compute domain knowledge, load on-demand
- **Hooks:** Preprocess data before Claude sees it

---

## 7. Session Management (Persistence & Resumption)

### Session Commands
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

### Session Features
- **Naming:** Sessions auto-get names; can be renamed with `/rename`
- **Cleanup:** Inactive sessions deleted after `cleanupPeriodDays` (default 30)
- **Persistence:** Stored by default; disable with `--no-session-persistence`
- **Context compaction:** Auto-triggered on context overflow
- **Checkpoint/rewind:** `/rewind` to restore to previous states

---

## 8. Skills & Custom Commands

### Skill Structure
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

### Skill Features
- **Frontmatter config:** Trigger, description, tool restrictions, arguments
- **Dynamic content:** String substitutions: `${PWD}`, `${ARGUMENT_NAME}`
- **Tool restriction:** Control which tools skill can access
- **Subagent delegation:** Run skill in isolated subagent context
- **Visibility control:** Restrict who can invoke via `permission` rules

---

## 9. Subagents (Delegation & Parallelization)

### Built-in Subagents
- `Explore`: Research and investigation
- `Plan`: Architecture and design planning
- `Bash`: High-volume shell operations
- Custom agents defined in `.claude/agents/` or via `--agents` flag

### Subagent Configuration
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

### Subagent Features
- **Parallel execution:** Multiple subagents run simultaneously
- **Isolated context:** Each has own context window
- **Cost isolation:** Verbose output stays in subagent context
- **Automatic delegation:** Based on description matching
- **Persistent memory:** Per-subagent memory can be enabled
- **Hook support:** Special `SubagentStart`, `SubagentStop` events

---

## 10. Docker & Container-Specific Guidance

### Devcontainer Reference Setup
- **Location:** GitHub Anthropics repo `.devcontainer/` directory
- **Files:** `devcontainer.json`, `Dockerfile`, `init-firewall.sh`
- **Key features:**
  - Node.js 20 with dev dependencies
  - ZSH with productivity tools (fzf, git, etc.)
  - Firewall: Whitelisted domains (npm, GitHub, Claude API only)
  - VS Code integration: Pre-configured extensions
  - Session persistence: Shell history preserved

### Container Best Practices
- **Headless mode:** Use `claude -p --output-format stream-json --verbose` for JSON streaming
- **Session resumption:** Capture `system.init` event for session ID, use `--resume SESSION_ID`
- **Task completion signals:** See [`docs/archipelago/adapter_protocol_spec.md`](../archipelago/adapter_protocol_spec.md) for the full protocol
- **Permissions in containers:** Use `--dangerously-skip-permissions` (safe in isolated container)
- **MCP in containers:** Configure via `--mcp-config` flag or `.mcp.json`

### Container Execution Patterns
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

## 11. Structured Outputs & Validation

### JSON Schema Support
```bash
claude -p \
  --output-format json \
  --json-schema '{"type":"object","properties":{"functions":{"type":"array","items":{"type":"string"}}},"required":["functions"]}' \
  "Extract function names from auth.py"
```

### Output Parsing with jq
```bash
# Extract text result
claude -p "Summarize" --output-format json | jq -r '.result'

# Extract structured output
claude -p "Extract data" --output-format json | jq '.structured_output'

# Stream tokens as they arrive
claude -p "Write poem" --output-format stream-json --verbose --include-partial-messages | \
  jq -rj 'select(.type == "stream_event" and .event.delta.type? == "text_delta") | .event.delta.text'
```
