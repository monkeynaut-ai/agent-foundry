# Claude Code Docker Worker - Testing Notes

## How to use this document

- **Worker CLAUDE.md source material** — The protocol details (ICRNL, `\r` vs `\n`, trust prompt behavior) inform what goes in the in-container worker's CLAUDE.md.
- **Onboarding context** — Point a new Claude Code session at this doc to give it the full history of what was tried, what failed, and why. Saves re-discovery.
- **Architecture decision records** — The Decisions section functions as an ADR log. As the system grows, individual ADRs can be split into separate files.
- **Regression prevention** — The "confirmed non-working approaches" tables document dead ends with issue links, preventing future contributors from re-attempting them.
- **Integration test specs** — The validation sections describe exact input/output sequences that can be turned into automated integration tests.

---

## 2026-03-04: Initial Docker Image Build & Interactive Test

### Image Build

Built `archipelago-cc-worker:latest` from `docker/Dockerfile`. Key details:

- Base image: `python:3.13-slim`
- Claude Code version installed: **2.1.68**
- Non-root user `claude` (1000:1000)
- Includes: git, curl, jq
- Settings at `/home/claude/.claude/settings.json` pre-allow Bash, Read, Edit, Write, Glob, Grep
- Entrypoint: `entrypoint.sh` runs `claude -p "$@"` (headless/print mode)

### Running Interactively (Option A)

To bypass the entrypoint and get an interactive Claude Code session:

```bash
docker run -it --rm \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  --entrypoint claude \
  archipelago-cc-worker:latest
```

This overrides the entrypoint (which uses `-p` headless mode) and launches Claude Code in its default interactive mode with a TTY.

### Observation: First-Run Setup Flow

When starting Claude Code interactively for the first time in the container, it presents a setup wizard:

1. **Text style selection** - cosmetic preference
2. **Login method** - offers API key or Claude subscription (OAuth)

#### Authentication Decision

**Decision: Use Claude subscription (OAuth) instead of `ANTHROPIC_API_KEY`.**

- API key usage is billed at API rates (more expensive)
- Claude subscription (Pro/Max) uses existing subscription quota
- OAuth flow requires browser authorization — Claude Code provides a URL since it can't open a browser inside the container

#### OAuth Flow in Container

1. Claude Code outputs a URL to the terminal
2. User pastes URL in host browser
3. Browser shows authorization page → click "Authorize"
4. Browser presents an authentication code
5. User copies code back into the container terminal
6. Login succeeds

#### Post-Login Steps

1. "Press enter to continue" (after login success)
2. Security notes displayed → "Press enter to continue"
3. Workspace access — shows `/workspace` as the volume
4. Trust prompt for the project → confirm to proceed
5. Now in interactive Claude Code session

#### Implications for Automated (Headless) Mode

The current entrypoint uses `claude -p` (headless). Key questions to resolve:

- **Auth persistence**: Can we mount the OAuth credentials from the host into the container so the setup wizard is skipped on subsequent runs? Credentials likely live in `~/.claude/` inside the container.
- **First-run bypass**: The setup wizard (text style, login) would block headless mode. Need a pre-authenticated state baked in or mounted.
- **API key vs OAuth for automation**: If we want fully unattended operation, API key is simpler (just pass env var). OAuth requires an initial interactive auth step but is cheaper under a subscription.

### Observation: Container Environment Inventory

Explored the running container via `/plugins`, `/model`, bash shell, and various slash commands.

#### Model & Configuration

- **Model**: Opus 4.6, medium effort (default)
- **Sandbox**: Disabled — missing dependencies: `bubblewrap`, `socat`, `seccomp`
  - Seccomp is required to block unix domain sockets
  - These need to be added to the Dockerfile's `apt-get install` if we want sandbox support

#### Plugins & Extensions

- **No plugins installed**
- Claude Code marketplace is accessible (official plugins available)
- **No custom agents** — built-in agents only
  - We have custom agents we could include in the image (baked in) or mount at runtime
  - Decision needed: bake vs mount (mount is more flexible for iteration)
- **No skills installed**

#### Workspace & Filesystem

- `/workspace` is empty (as expected — no repo cloned yet)
- `/home/claude/.claude/` is the Claude Code home directory
- **No CLAUDE.md** file present — we should provide one for the worker context
- **Projects file** retains session history — potential for a reinforcement loop:
  - Analyze session history + output to improve Archipelago prompts/behavior over time

#### Features to Investigate

| Feature | Why It Matters |
|---|---|
| `/chrome` | Purpose unclear — investigate what it enables inside Claude Code |
| `/batch` | May be useful for submitting multiple prompts or queuing work |
| **Conversation renaming** | Could help organize/track sessions within the container |
| **Claude Slack app** | Could enable interaction with the world outside the container — notifications, approvals, status updates back to the team |

#### Dockerfile Improvements Identified

1. **Add sandbox dependencies**: `bubblewrap`, `socat`, `libseccomp-dev` (or `seccomp` package)
2. **Include a worker CLAUDE.md**: Give Claude Code context about its role as an Archipelago worker
3. **Custom agents**: Either bake into image or establish a mount convention
4. **Skills**: Determine which skills to pre-install for the worker use case

---

## Investigation: Three Key Questions

### Q1: Repo Access — Clone vs Mount?

**Options:**

| Approach | Pros | Cons |
|----------|------|------|
| **Mount host repo** (`-v /path/to/repo:/workspace`) | Instant, no clone time. Changes visible on host immediately. Easy for dev/test. | Tight coupling to host filesystem. Container writes affect host. Permission issues (uid mapping). |
| **Clone inside container** (current handler approach) | Clean isolation. Matches production flow. No host coupling. | Slower startup. Needs git credentials/SSH keys. Network dependency. |
| **Mount as read-only + copy** | Isolation with fast start. No host side-effects. | Extra disk in container. Complexity. |

**Current handler behavior**: `docker_worker_handler` creates a named Docker volume and clones a repo into it via `git clone`. This is the production path.

**Recommendation for testing**: Mount the host repo for fast iteration now. Switch to clone for integration testing later.

```bash
docker run -it --rm \
  -v /home/markn/730alchemy/repos/agent-foundry/demo-archipelago:/workspace \
  --entrypoint claude \
  archipelago-cc-worker:latest
```

### Q2: Providing CLAUDE.md, Agents, Plugins, Skills

**Claude Code directory structure** (inside container at `/home/claude/.claude/`):

```
/home/claude/.claude/
├── CLAUDE.md                    # User-level instructions (loaded every session)
├── settings.json                # Already present in our image
├── agents/
│   └── <agent-name>/
│       └── <agent-name>.md      # Markdown + YAML frontmatter
├── skills/
│   └── <skill-name>/
│       └── SKILL.md             # Markdown + YAML frontmatter
└── rules/
    └── *.md                     # Path-scoped conditional instructions
```

**Project-level** (at `/workspace/.claude/`):

```
/workspace/.claude/
├── CLAUDE.md                    # Project instructions (team-shared)
├── settings.json                # Project settings
├── agents/                      # Project-scoped agents
├── skills/                      # Project-scoped skills
└── rules/                       # Path-scoped rules
```

**Precedence** (highest to lowest): CLI flags > local project > shared project > user-level

**Strategy — two layers:**

1. **Bake into image** (`/home/claude/.claude/`): Worker-role CLAUDE.md, agents and skills that are stable and common to all Archipelago workers. These are the "platform" defaults.
2. **Mount or clone with project** (`/workspace/.claude/`): Project-specific CLAUDE.md, agents, skills, and rules. These come from the repo being worked on.

This mirrors how a developer has personal config (`~/.claude/`) plus project config (`.claude/` in repo).

**Agents format** — each agent is a Markdown file with YAML frontmatter:

```markdown
---
name: code-reviewer
description: Reviews code for quality and best practices
tools: Read, Grep, Glob, Bash
model: sonnet
---

You are a senior code reviewer. When invoked, analyze...
```

**Skills format** — similar, in `<skill-name>/SKILL.md`:

```markdown
---
name: batch
description: Run parallel work across worktrees
allowed-tools: Bash, Read, Write, Glob, Grep
---

Instructions for the skill...
```

### Q3: Automated Authentication with Claude Subscription

#### Clarification: What the OAuth Tokens Actually Are

The OAuth tokens authenticate against **claude.ai** (the consumer product) — your personal Claude account and subscription. They are **completely separate** from the Anthropic API platform (console.anthropic.com).

**Three distinct auth systems in Claude Code:**

| System | Identity | Billing | Method |
|--------|----------|---------|--------|
| **Claude subscription OAuth** | claude.ai account | Pro/Max/Teams subscription quota | Browser OAuth flow |
| **ANTHROPIC_API_KEY** | console.anthropic.com account | API pay-per-token | Static env var |
| **Cloud provider auth** | AWS/GCP/Azure IAM | Bedrock/Vertex/Foundry billing | Provider credentials |

When we logged in via OAuth in the container, we linked it to the user's personal claude.ai Pro/Max subscription. Usage counts against subscription quota, not API credits. This is why it's cheaper.

**Linux credential storage**: Two files required ([Issue #1736](https://github.com/anthropics/claude-code/issues/1736)):
- `~/.claude/.credentials.json` — OAuth tokens
- `~/.claude.json` — account info, onboarding state, install metadata

Without both files, Claude Code treats the session as a fresh install and prompts for login.

**The problem**: `claude -p` (headless mode) needs pre-existing auth. OAuth requires an interactive browser flow.

#### Research Findings: `setup-token` Solves This

The `claude setup-token` command generates a **long-lived OAuth token valid for ~1 year** that uses subscription credits (not API pay-per-token). This is the documented path for headless/container automation with a Claude subscription.

**Sources:**
- [Automating Claude Code auth without browser OAuth](https://gist.github.com/coenjacobs/d37adc34149d8c30034cd1f20a89cce9) — Full `setup-token` workflow
- [Avoid re-authenticating in Docker (Issue #1736)](https://github.com/anthropics/claude-code/issues/1736) — Files to persist
- [OAuth not persisting in Docker (Issue #22066)](https://github.com/anthropics/claude-code/issues/22066) — Known bug, workarounds
- [Device-code auth flow request (Issue #22992)](https://github.com/anthropics/claude-code/issues/22992) — Open feature request, not yet implemented
- [Official Authentication Docs](https://code.claude.com/docs/en/authentication) — Credential management reference
- [Docker sandbox docs](https://docs.docker.com/ai/sandboxes/agents/claude-code/) — Docker's official guidance
- [Claude Code Action with OAuth (GitHub Marketplace)](https://github.com/marketplace/actions/claude-code-action-with-oauth) — GitHub Actions OAuth integration
- [Claude Code SDK Docker auth docs](https://github.com/cabinlab/claude-code-sdk-docker/blob/main/docs/AUTHENTICATION.md) — Community Docker auth patterns

**Options for automation:**

#### Option A: `setup-token` + env var (RECOMMENDED)

**One-time setup** (on a machine with a browser):

1. Run `claude setup-token`
2. Complete the browser OAuth flow
3. Receive a token: `sk-ant-oat01-xxxxx...xxxxx`
4. Extract account info from `~/.claude.json`

**Container usage** (fully headless, no browser needed):

```bash
docker run --rm \
  -e CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-xxxxx \
  archipelago-cc-worker:latest "implement the feature"
```

Also need a minimal `~/.claude.json` with `"hasCompletedOnboarding": true` to bypass the setup wizard. This can be baked into the image or mounted.

**Pros**: Uses subscription credits (cheaper). Token lasts ~1 year. No browser needed at runtime.
**Cons**: Token must be regenerated annually. Concurrent container behavior undocumented.

**Important**: Never set both `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_API_KEY` simultaneously — causes auth conflicts.

#### Option B: API key for headless, subscription for interactive

- Use `ANTHROPIC_API_KEY` env var for automated pipeline runs (no setup wizard, no token expiry concern)
- Use OAuth for interactive/development sessions
- Trade-off: API key costs more but is fully unattended and well-documented

#### Option C: Mount credentials volume

1. Run container interactively once, complete OAuth flow
2. Persist `~/.claude/` and `~/.claude.json` via named Docker volume
3. Mount into subsequent containers

```bash
# First time: interactive auth
docker run -it --rm \
  -v claude-auth:/home/claude/.claude \
  -v claude-json:/home/claude/.claude.json \
  --entrypoint claude archipelago-cc-worker:latest

# Subsequent runs: headless with persisted auth
docker run --rm \
  -v claude-auth:/home/claude/.claude \
  -v claude-json:/home/claude/.claude.json \
  archipelago-cc-worker:latest "implement the feature"
```

**Risk**: Known bug where host Claude Code usage can delete shared credentials ([Issue #1736](https://github.com/anthropics/claude-code/issues/1736)).

#### Option D: `apiKeyHelper` setting

Claude Code supports a `apiKeyHelper` setting — a script that returns credentials. Could script OAuth token refresh, but this is undocumented territory.

#### Updated Recommendation

**Option A (`setup-token`)** is now the clear winner for production:
- Subscription pricing (cheapest)
- 1-year token lifespan (low maintenance)
- Single env var (simple container config)
- No volume mounting complexity

**Option B (API key)** remains the fallback if OAuth proves unreliable in multi-container scenarios.

**Headless mode flags** (skip all interactive prompts):

```bash
claude -p "your prompt" \
  --output-format stream-json \
  --allowedTools "Read,Bash,Edit,Write,Glob,Grep" \
  --dangerously-skip-permissions \
  --max-turns 10
```

- `-p` / `--print`: Non-interactive, no setup wizard, no security prompts
- `--dangerously-skip-permissions`: Skip all tool permission prompts
- `--output-format stream-json`: Streaming structured output for parsing
- `--max-turns`: Limit agentic iterations

## E2E Wiring Decisions

### State Bridge (handler fallback)

The approval gate outputs individual keys (`feature_spec`, `test_plan`, etc.) but the docker worker handler originally required a pre-assembled `worker_input` dict. Rather than add a dedicated bridge node, the handler now falls back to constructing `WorkerInput` from individual state keys when `worker_input` is absent. This preserves backward compat — explicit `worker_input` still works.

### Prompt Delivery

The handler's trust-confirmation thread now also sends the feature spec as a prompt to Claude Code's stdin after dismissing the trust prompt. A `_build_prompt()` helper formats the `WorkerInput.feature_spec` dict into a human-readable prompt string.

Sequence: launch session → retry `\r` every 2s until trust accepted → send prompt + `\r`.

### .env Loading

`dotenv.load_dotenv()` is called at the top of `cli.py:main()` so `CLAUDE_CODE_OAUTH_TOKEN` (and other env vars) are available to the container manager when it forwards env vars to the Docker container.

### Feature Investigation Results

| Feature | Finding |
|---|---|
| `/chrome` | Connects Claude Code to Chrome browser for web automation, testing, screenshots. Requires Chrome + Claude in Chrome extension. Not useful inside headless container. |
| `/batch` | A custom skill (not built-in) — researches a change then executes in parallel across 5-30 isolated worktree agents, each opening a PR. Potentially very useful for Archipelago's parallel work pattern. |
| **Slack app** | Could enable notifications/approvals from outside the container. Worth investigating for the interrupt/approval flow. |

---

## Decisions

### Decided

1. **Auth strategy**: Use `claude setup-token` + `CLAUDE_CODE_OAUTH_TOKEN` env var (Option A). Subscription pricing, 1-year token, simple. Fall back to `ANTHROPIC_API_KEY` if multi-container issues arise.

2. **Adapter-to-Archipelago transport**: WebSocket now, gRPC streaming later.

   The in-container PTY adapter needs a transport to communicate with Archipelago. Archipelago will have an internal event/notification system where any graph node can react to adapter output. The adapter's job is simple: bridge PTY to a single transport endpoint. Fan-out to nodes happens inside Archipelago's orchestration layer.

   **Chosen**: WebSocket — message-framed out of the box (no custom delimiter/length-prefix protocol), bidirectional (output events + input commands on one connection), lightweight, easy to debug.

   **Future**: gRPC streaming — when we need strong typing and structured messages (protobuf).

   **Rejected permanently**:
   - TCP socket — raw bytes with no framing, would require a custom protocol layer
   - HTTP + SSE — unidirectional output stream, input needs a separate channel
   - Redis/NATS/ZMQ — message brokers add infrastructure and put pub/sub responsibility inside the container adapter, violating separation of concerns. The adapter should not know about Archipelago's internal event distribution.

3. **Application-level protocol for adapter↔Archipelago communication.**

   The raw WebSocket transport (decision #2) carries structured JSON messages defined by a transport-agnostic protocol. This protocol is a standard for communication with any remote coding agent — not Docker-specific.

   **Key design decisions:**

   - **Structured messages only, no raw bytes.** The adapter parses interrupt markers and strips ANSI escape codes locally. Archipelago receives only typed JSON messages (`output`, `interrupt`, `status`, `input`, `control`). It never scans raw PTY output.
   - **Adapter connects outward to Archipelago** (not the other way around). Archipelago starts a WebSocket server; the adapter connects to it. Works through NAT, scales to N containers, natural fit for future SSH adapters.
   - **Per-handler WebSocket server** to start. Each handler invocation starts its own ephemeral server. Session ID in the URL path future-proofs for migration to a centralized server when the event bus is built.
   - **ICRNL encapsulated in the adapter.** Archipelago sends `\n`-terminated text in input messages. The adapter converts `\n` → `\r` before writing to the PTY. The `\r` vs `\n` concern is invisible to the orchestrator.
   - **Interrupt parsing moves to the adapter.** The adapter detects `ARCHIPELAGO_NEED_*` markers in PTY output and emits structured `interrupt` messages. Marker lines are not sent as `output` messages.

   Full specification: `docs/demo-archipelago/adapter_protocol_spec.md`

4. **Container entrypoint: adapter as PID 1, remove `sleep infinity`.**

   The current `create_container()` overrides the Dockerfile entrypoint with `sleep infinity`, then reaches in via `docker exec` to start Claude Code. This is not a Docker best practice — it breaks health checks, signal handling, and restart policies.

   **Change:** The container's Dockerfile entrypoint runs the adapter directly. The adapter spawns Claude Code and connects to Archipelago over WebSocket. Container lifecycle becomes clean: start → adapter runs → CC exits → container exits. Docker exec is retained only for utility commands (git clone, image validation, crash recovery).

   **Four uses of Docker exec today:**
   | # | What | Stays? |
   |---|---|---|
   | 1 | Launch entrypoint.sh with PTY + stdin/stdout channel | **Replaced by WebSocket** |
   | 2 | `git clone` for workspace setup | Yes |
   | 3 | `which <cmd>` for image validation | Yes |
   | 4 | `git rev-parse/diff` for crash recovery | Yes |

### Open

5. **What goes in the worker CLAUDE.md?** Role description, output format (progress markers), constraints, Archipelago protocol
6. **Which agents/skills to bake into the image?** Need to inventory what we have and what the worker needs
7. **Sandbox deps**: Worth adding to Dockerfile? Defense-in-depth vs overhead inside already-sandboxed Docker
8. **Performance/limits**: Message size limits, latency requirements, throughput targets for the protocol (deferred)

---

## Changes Implemented: OAuth Token Support

### Files Changed

| File | Change |
|------|--------|
| `docker/claude.json` | **New** — `{"hasCompletedOnboarding": true}` bypasses first-run wizard |
| `docker/Dockerfile` | Added `COPY claude.json /home/claude/.claude.json` |
| `docker/entrypoint.sh` | Added auth validation: requires exactly one of `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`, fails fast with clear error if both or neither set |
| `src/archipelago/docker_worker/container.py` | **Bug fix**: env var forwarding now reads from `os.environ` (was reading from nonexistent `client.environment`). Added `CLAUDE_CODE_OAUTH_TOKEN` to allowlist. |
| `tests/archipelago/test_docker_worker_container.py` | Updated env var test to use `monkeypatch.setenv` instead of mock `client.environment` |

### Bug Fixed

`ContainerManager.create_container()` was filtering env vars from `self._client.environment`, which doesn't exist on real Docker SDK clients. This meant **no env vars ever reached the container** — including `ANTHROPIC_API_KEY`. Fixed to read from `os.environ` instead.

### Container Usage

```bash
# With subscription token (recommended — cheaper)
docker run --rm \
  -e CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-xxxxx \
  archipelago-cc-worker:latest "implement the feature"

# With API key (fallback)
docker run --rm \
  -e ANTHROPIC_API_KEY=sk-ant-xxxxx \
  archipelago-cc-worker:latest "implement the feature"
```

### Test Results

429 passed, 0 failures (full suite).

### Validation: Headless Run with OAuth Token

Confirmed working end-to-end:

1. Generated token via `claude setup-token` on host (interactive, one-time browser flow)
2. Ran: `docker run --rm -e CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-xxxxx archipelago-cc-worker:latest "say hello"`
3. **Result**: Claude Code authenticated via subscription, processed the prompt, printed the response to stdout, and the container exited cleanly.

This validates:
- `claude.json` onboarding bypass works (no setup wizard)
- `CLAUDE_CODE_OAUTH_TOKEN` env var is picked up by Claude Code
- Entrypoint auth check passes with a single auth method
- `claude -p "$@"` headless mode works as expected
- Container lifecycle is clean (start → process → exit)

### Validation: Interactive Mode with TTY Detection

Updated entrypoint to detect TTY (`-t 0`): runs `claude` (interactive) with TTY, `claude -p` (headless) without.

```bash
docker run -it --rm \
  -e CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-xxxxx \
  archipelago-cc-worker:latest
```

**Result**: Claude Code opens in interactive mode, stays open, accepts prompts, responds with streaming output.

**Gotcha**: Token must include the full `sk-` prefix. Quoting the env var value is recommended to prevent shell interpretation:
```bash
-e "CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-xxxxx"
```

### Validation: Parallel Containers with Same Token

Tested running two containers simultaneously with the same `CLAUDE_CODE_OAUTH_TOKEN`.

**Result**: Both sessions authenticate and respond to prompts independently. No auth conflicts or token invalidation.

This confirms:
- A single `setup-token` output can be shared across multiple concurrent containers
- Archipelago can safely spin up parallel Docker workers using one subscription token
- No need for per-container token generation

### PTY Input Pipeline: How Programmatic Keystrokes Reach Claude Code

Claude Code's TUI is built on **Ink** (React for terminals). The input path:

1. Archipelago writes bytes to the PTY socket via `sendall()`
2. Bytes pass through the PTY **line discipline** (kernel-level termios processing)
3. Ink's `parse-keypress.ts` maps raw bytes to key events: `\r` (0x0D) → `{ name: 'return' }`
4. `useInput` hook fires callback with `key.return = true`
5. The input component's `onSubmit` triggers only when `key.return === true`

**Critical detail**: Ink checks for `\r` (0x0D), NOT `\n` (0x0A). The PTY's `ICRNL` termios flag converts `\r` → `\n` in the line discipline before Ink sees it. So by default, Ink never receives `\r`, never sets `key.return = true`, and submit never fires.

**Fix implemented**: `stty -icrnl` in `entrypoint.sh` disables the ICRNL flag so `\r` passes through unchanged. The handler sends `\r` instead of `\n` for all PTY submissions.

**Sources**:
- [Ink parse-keypress.ts](https://github.com/vadimdemedes/ink/blob/master/src/parse-keypress.ts) — `\r` → return key mapping
- [Ink useInput hook](https://github.com/vadimdemedes/ink/blob/master/src/hooks/use-input.ts) — key.return handling
- [ink-text-input source](https://github.com/vadimdemedes/ink-text-input/blob/master/source/index.tsx) — onSubmit on key.return
- [Issue #15553: Programmatic Input Submission](https://github.com/anthropics/claude-code/issues/15553) — workarounds, root cause analysis

### Issue: Workspace Trust Prompt

Claude Code always shows a workspace trust confirmation prompt on startup ("Do you trust this folder?"), requiring Enter to proceed. This is a security feature with **no official bypass**.

**Confirmed non-working approaches** (via multiple GitHub issues):

| Approach | Status | Source |
|----------|--------|--------|
| `--dangerously-skip-permissions` flag | Does NOT skip trust prompt | [Issue #28506](https://github.com/anthropics/claude-code/issues/28506) |
| `trustedDirectories` in settings.json | Never implemented | [Issue #12737](https://github.com/anthropics/claude-code/issues/12737) |
| Pre-configuring `.claude.json` with projects | Doesn't work | [Issue #9113](https://github.com/anthropics/claude-code/issues/9113) |
| Trust settings persistence across sessions | Not persisted | [Issue #21283](https://github.com/anthropics/claude-code/issues/21283) |
| Trusted workspace patterns (glob) | Open feature request | [Issue #23109](https://github.com/anthropics/claude-code/issues/23109) |
| Permanent directory trust | Open feature request | [Issue #29285](https://github.com/anthropics/claude-code/issues/29285) |

**Current solution**: The handler's daemon thread sends `\r` to the PTY to dismiss the trust prompt. Handled in `docker_worker_handler()`, not in the entrypoint or Dockerfile.

**Known issue**: The trust confirmation `\r` has a timing race — the entrypoint's version check fires the handler's `first_output` event, but Claude Code (Node.js) takes several more seconds to start and render the trust prompt. The `\r` sent 1 second after `first_output` arrives before the trust prompt renders. **Deferred**: needs a retry loop that sends `\r` every ~2 seconds until output indicates trust was accepted.

**Prompt submission works correctly** — the feature spec prompt + `\r` submits as expected after trust is manually confirmed.

**Note on `--dangerously-skip-permissions`**: If this flag is set, Claude Code displays a **second** confirmation asking "are you sure you want to bypass all permissions?" where Enter means **no** (deny). To confirm, you must arrow-down then Enter. This two-step confirmation with a non-obvious default makes it unreliable for automation. Avoid using this flag in the Archipelago pipeline.

### Three Approaches Researched for Programmatic Input

| Approach | Description | Status |
|----------|-------------|--------|
| **A: Disable ICRNL** | `stty -icrnl` + send `\r` instead of `\n` | **Implemented**. Prompt submission works. Trust confirmation needs retry loop. |
| **B: Escape + Enter** | Send text, wait 300ms, send `\x1b` (dismiss autocomplete), wait 100ms, send `\r` | Backup if autocomplete intercepts Enter. From [Issue #15553](https://github.com/anthropics/claude-code/issues/15553). |
| **C: stream-json protocol** | `claude -p --input-format stream-json --output-format stream-json` — NDJSON on stdin/stdout | **Cleanest long-term**. Bypasses Ink TUI entirely. Fully OAuth-compatible. Same protocol as Agent SDK. See [CLI reference](https://code.claude.com/docs/en/cli-reference). |

---

## Changes Implemented: ICRNL Fix for PTY Input Submission

### Files Changed

| File | Change |
|------|--------|
| `docker/entrypoint.sh` | Added `stty -icrnl` before launching Claude Code — disables carriage return → newline conversion in PTY line discipline |
| `src/archipelago/docker_worker/handler.py` | Changed `\n` → `\r` in trust confirmation, prompt submission (`_confirm_trust_and_prompt`), and stdin forwarding (`_forward_stdin`) |
| `tests/archipelago/test_docker_worker_handler.py` | 4 new tests in `TestICRNLFix` class; updated assertion in existing trust test to expect `\r` |

### Test Results

437 passed, 0 failures (full suite).

### Validation: Interactive PTY Session

Tested with rebuilt Docker image. User can interact with Claude Code running in the container — typing and submitting prompts works. The handler's prompt submission (`prompt + "\r"`) correctly triggers Ink's submit. Trust confirmation `\r` has a timing issue (deferred — see "Known issue" above).
