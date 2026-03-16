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

The adapter protocol spec (`docs/archipelago/adapter_protocol_spec.md:3-22`) explicitly requires a CLAUDE.md with task completion protocol instructions. Without it:
- Claude Code won't emit `ARCHIPELAGO_TASK_COMPLETE` markers
- Inside-out completion detection fails entirely
- Every session requires external `control:complete` to proceed

The Dockerfile copies `settings.json` and `claude.json` but **no CLAUDE.md** at either `/home/claude/.claude/CLAUDE.md` (user-level) or meant to be in `/workspace/.claude/CLAUDE.md` (project-level). Our own notes at `docs/archipelago/docker-testing-log.md` flag this: "No CLAUDE.md file present."

### 2. No sandbox dependencies

`docs/archipelago/docker-testing-log.md` identifies that sandbox mode is broken inside the container because `bubblewrap`, `socat`, and `libseccomp-dev` are missing. The `settings.json` sets `"sandbox": {"enabled": true, "enableWeakerNestedSandbox": true}` but the actual dependencies aren't installed. This means sandbox is silently disabled at runtime -- the setting is a lie.

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

`docs/archipelago/docker-testing-log.md` notes "No custom agents" and "No skills installed." The directory structure supports `/home/claude/.claude/agents/` and `/home/claude/.claude/skills/`, but nothing is copied. The `/batch` skill (parallel worktree execution) was identified as "potentially very useful for Archipelago's parallel work pattern."

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

## Appendix: Claude Code CLI Reference

The full Claude Code CLI surface area reference (flags, settings.json, MCP, hooks, sessions, skills, subagents, Docker guidance) has been extracted to [`docs/reference/claude-code-cli-reference.md`](reference/claude-code-cli-reference.md).
