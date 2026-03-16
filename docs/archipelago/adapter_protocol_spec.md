# Feature Specification: Adapter-Orchestrator Communication Protocol

> **IMPORTANT — CLAUDE.md Instruction Required**
>
> The worker container's CLAUDE.md must include the following instruction so that Claude Code signals task completion to the adapter:
>
> ```markdown
> ## Task Completion Protocol
>
> You are running inside an Archipelago worker container. When you have completed
> all requirements in the feature spec and verified tests pass, you MUST output
> the following marker on its own line as the last line of your response:
>
> ARCHIPELAGO_TASK_COMPLETE
>
> This is a required part of the workflow protocol. The marker signals the
> orchestrator to run the gate check. Do not output this marker until you are
> confident the work is complete. If you are unsure or need clarification, ask
> instead.
> ```
>
> Without this instruction, the adapter cannot detect inside-out task completion. The gate node will still catch missing signals, but sessions will require an external `control:complete` to proceed.

## Objective

Define and implement a transport-agnostic application protocol for structured, bidirectional communication between a remote coding agent adapter and the Archipelago orchestrator. Replace the current Docker exec-based stdin/stdout channel (`SessionManager.launch_session()` via `exec_create`/`exec_start`) with a WebSocket connection where the in-container adapter emits structured JSON messages. The orchestrator receives only typed messages -- never raw bytes.

### Headless Mode (Preferred)

The headless adapter (`lab/headless_adapter.py`) uses `claude -p --output-format stream-json --verbose` instead of spawning a PTY. Claude Code outputs newline-delimited JSON events (types: `system`, `assistant`, `result`, `rate_limit_event`). The adapter maps these to protocol messages. Multi-turn conversations use `--resume SESSION_ID`. This eliminates ANSI stripping, TUI noise filtering, trust confirmation, and ICRNL conversion.

### PTY Mode (Legacy)

The PTY adapter (`lab/adapter.py`) spawns Claude Code in a PTY via pexpect and scrapes TUI output. It bridges the PTY and emits structured JSON messages, parsing interrupt markers and stripping ANSI codes locally. This mode is retained for backward compatibility but is not recommended for new deployments.

### Success Criteria

1. Protocol message types are defined as Pydantic v2 models in `src/archipelago/docker_worker/protocol.py`, covering all communication in both directions (adapter-to-orchestrator and orchestrator-to-adapter).
2. The adapter (`lab/adapter.py`) reads raw PTY output, strips ANSI escape codes, detects interrupt markers, and emits structured JSON messages over a WebSocket -- Archipelago never receives raw bytes.
3. The `docker_worker_handler` connects to the adapter's WebSocket (instead of using Docker exec for stdin/stdout) and consumes structured messages, preserving all existing behavior: output collection, interrupt handling, trust confirmation, prompt delivery, timeout, and progress collection.
4. The container entrypoint runs the adapter as PID 1. The `sleep infinity` override in `ContainerManager.create_container()` is removed. Docker exec is retained only for utility commands (git clone, image validation, crash recovery git state).
5. A session ID is included in the WebSocket URL path for future migration to a centralized server.
6. The protocol is transport-agnostic: message schemas and exchange rules do not reference Docker, PTY, WebSocket, or any specific transport.
7. All existing tests (426 in `tests/`, 12 in `lab/`) remain green. No regressions.

---

## Constraints

### Technical

- **Python 3.13** (per `pyproject.toml`), PDM for package management.
- **Threading model**: The codebase uses `threading`, not `asyncio`. The adapter uses `websockets.sync.server`; the handler will use `websockets.sync.client`. No asyncio introduction.
- **Existing `websockets` dependency**: Already in use (`websockets.sync.server` in `lab/adapter.py`, `websockets.sync.client` in `lab/test_ws_adapter.py`). No new transport dependencies.
- **Handler signature unchanged**: `def docker_worker_handler(state: dict[str, Any]) -> dict[str, Any]`. The handler still blocks until the session completes or a breakpoint is triggered.
- **Pydantic v2 models** for all protocol messages. JSON serialization via `model_dump_json()` / `model_validate_json()`.
- **Docker exec retained for utility commands**: `container.exec_run()` stays for git clone (`container.py:101`), image validation (`container.py:124`), and crash recovery git state (`recovery.py:102-108`). Only the PTY communication exec (`session.py:45-55`) is replaced.
- **Interrupt model compatibility**: Protocol interrupt messages must carry the same information as `ClarificationRequest`, `PermissionRequest`, and `UpdateAvailable` (defined in `models.py:85-107`). The handler deserializes protocol interrupt messages into these existing models.
- **ICRNL handling moves to the adapter**: The adapter converts `\n` in input messages to `\r` before writing to the PTY. Archipelago sends natural `\n`-terminated text. The `\r` vs `\n` concern is encapsulated in the adapter.
- **ANSI stripping in the adapter**: No ANSI stripping exists in the codebase today. The adapter will strip ANSI escape codes from PTY output before emitting `output` messages.
- **Per-handler WebSocket server**: The handler starts a WebSocket server on an ephemeral port, passes the URL to the container via env var (`ARCHIPELAGO_WS_URL`), and the adapter connects outward to it. Session ID in the URL path for future centralized server migration.
- **Container entrypoint change**: The Dockerfile's `ENTRYPOINT` already points to `entrypoint.sh`. Currently overridden by `entrypoint="sleep", command="infinity"` in `create_container()`. This override is removed. The entrypoint script is updated to run the adapter, which spawns Claude Code.
- **`ARCHIPELAGO_WS_URL` added to env allowlist**: `container.py` `DEFAULT_ENV_ALLOWLIST` must include this new env var so it reaches the container.

### Scope

- **In scope**: Protocol message models, ANSI stripping utility, adapter rewrite (structured messages over WebSocket), handler rewrite (WebSocket client replacing Docker exec channel), `ContainerManager.create_container()` entrypoint change, entrypoint script update, `DEFAULT_ENV_ALLOWLIST` update, all associated tests.
- **Out of scope**: Centralized WebSocket server (future), event bus design (future), SSH adapter (future), reconnection/retry on WebSocket drop (future -- for now, a dropped connection means session failure), TLS/auth on the WebSocket (unnecessary within Docker network), multi-container parallelism, changes to `InterruptHandler` or `InterruptDetector` (they continue to work as-is, fed by protocol messages instead of raw output callbacks).

### Quality

- TDD throughout: tests written before implementation, red-green-refactor.
- Each PR independently mergeable; system stays in a working state after each merge.
- Each commit atomic and focused on a single concern.
- Test naming follows Given/When/Then convention.
- WebSocket tests in `lab/` use `cat` as a mock subprocess (existing pattern).
- Handler tests mock the WebSocket connection (no real adapter needed).
- All 426 existing tests remain green.

### Time

- PR 1 (protocol models) is the foundation; all subsequent PRs depend on it.
- PR 2 (adapter rewrite) depends on PR 1.
- PR 3 (handler rewrite) depends on PR 1 and PR 2.
- PR 4 (container entrypoint integration) depends on PR 3.

---

## Protocol Specification

### Message Format

Each message is a JSON object sent as a WebSocket **text frame**. One JSON object per WebSocket message. No NDJSON, no binary framing, no length prefixes. WebSocket provides message framing natively.

Every message has a `type` field that identifies the message kind. An optional `session_id` field is present on all messages for routing (future use). A `timestamp` field (Unix epoch float) is present on all adapter-to-orchestrator messages.

### Message Types: Adapter to Orchestrator

#### `output`

Agent text output, ANSI-stripped. Emitted per-line (the adapter buffers on `\n` boundaries, matching the current `SessionManager._stream_output` behavior).

```json
{
  "type": "output",
  "session_id": "abc-123",
  "text": "Running pytest... 5 passed",
  "stream": "stdout",
  "timestamp": 1709654321.123
}
```

Fields:
- `type`: Literal `"output"`
- `session_id`: `str` -- session identifier
- `text`: `str` -- one line of output, ANSI escape codes stripped, no trailing newline
- `stream`: Literal `"stdout"` | `"stderr"` -- which stream this came from (PTY merges them, so this will typically be `"stdout"`)
- `timestamp`: `float` -- monotonic timestamp from the adapter

#### `interrupt`

A structured interrupt detected in the agent's output. The adapter parses the `ARCHIPELAGO_NEED_*` marker and emits the parsed payload.

```json
{
  "type": "interrupt",
  "session_id": "abc-123",
  "interrupt_type": "clarification",
  "payload": {
    "question": "Which database driver?",
    "options": ["pg", "mysql"],
    "default": "pg",
    "blocking": true
  },
  "timestamp": 1709654322.456
}
```

Fields:
- `type`: Literal `"interrupt"`
- `session_id`: `str`
- `interrupt_type`: Literal `"clarification"` | `"permission"` | `"update_available"`
- `payload`: `dict` -- the parsed JSON payload from the marker line, matching the schema of `ClarificationRequest`, `PermissionRequest`, or `UpdateAvailable`
- `raw_line`: `str` -- the original marker line (for debugging/audit)
- `timestamp`: `float`

#### `status`

Lifecycle state changes of the agent process.

```json
{
  "type": "status",
  "session_id": "abc-123",
  "status": "started",
  "exit_code": null,
  "detail": "Claude Code process launched",
  "timestamp": 1709654320.000
}
```

Fields:
- `type`: Literal `"status"`
- `session_id`: `str`
- `status`: Literal `"started"` | `"running"` | `"turn_complete"` | `"completed"` | `"exited"` | `"error"`
- `exit_code`: `int | None` -- present when `status` is `"turn_complete"`, `"completed"`, or `"exited"`
- `detail`: `str` -- human-readable description (e.g., `stop_reason` from Claude Code on `turn_complete`)
- `timestamp`: `float`

The adapter emits:
- `started` when the adapter connects to the orchestrator
- `running` when a turn begins (prompt sent to Claude Code)
- `turn_complete` when Claude Code finishes a turn (includes `exit_code` and `stop_reason` in `detail`). The adapter stays alive for more turns.
- `completed` when the adapter detects the `ARCHIPELAGO_TASK_COMPLETE` marker in Claude's output (inside-out signal), or when the orchestrator sends `control:complete` (outside-in signal). **The container stays alive after `completed`** — the gate node may resume the session (gate rejected) or terminate it (gate accepted).
- `exited` when the adapter shuts down (after `control:terminate` or `control:kill`)
- `error` when the adapter encounters an internal error (e.g., timeout, failed to connect)

### Message Types: Orchestrator to Adapter

#### `input`

Text to send to the agent's stdin.

```json
{
  "type": "input",
  "session_id": "abc-123",
  "text": "pg\n"
}
```

Fields:
- `type`: Literal `"input"`
- `session_id`: `str`
- `text`: `str` -- text to write to stdin. The adapter converts `\n` to `\r` before writing to the PTY (ICRNL encapsulation).

#### `control`

Control commands for the adapter/agent process.

```json
{
  "type": "control",
  "session_id": "abc-123",
  "command": "resize",
  "args": {"rows": 50, "cols": 120}
}
```

Fields:
- `type`: Literal `"control"`
- `session_id`: `str`
- `command`: Literal `"resize"` | `"terminate"` | `"kill"` | `"complete"`
- `args`: `dict` -- command-specific arguments
  - `resize`: `{"rows": int, "cols": int}`
  - `terminate`: `{}` -- adapter shuts down gracefully, sends `status:exited`
  - `kill`: `{}` -- adapter shuts down immediately, sends `status:exited`
  - `complete`: `{}` -- outside-in completion signal. The adapter sends `status:completed` but **stays alive**. Used when the orchestrator node, human, or external component determines the task is done. The gate node then sends `terminate` (if accepted) or `input` (if rejected, to resume the session).

### Exchange Patterns

- **Output streaming**: The adapter emits `output` messages as the agent produces text. In headless mode, text blocks from `assistant` events are sent as output; tool usage is summarized. In PTY mode, output is ANSI-stripped and sent line-by-line. Fire-and-forget; no acknowledgment from the orchestrator.
- **Interrupt detection**: When the adapter detects an `ARCHIPELAGO_NEED_*` marker in the output, it emits an `interrupt` message instead of (not in addition to) an `output` message for that line.
- **Task completion detection (inside-out)**: When the adapter detects `ARCHIPELAGO_TASK_COMPLETE` in Claude's output, it strips the marker, sends any remaining text as `output`, then sends `status:completed`. The adapter stays alive — the gate node decides whether to resume or terminate.
- **Task completion signal (outside-in)**: The orchestrator sends `control:complete` when a human, gate node, or external component determines the task is done. The adapter sends `status:completed` and stays alive.
- **Multi-turn input**: The orchestrator sends `input` messages at any time. In headless mode, the adapter spawns a new `claude -p --resume SESSION_ID` subprocess with the input text. In PTY mode, the text is written to stdin with `\n` → `\r` conversion.
- **Turn lifecycle**: After each Claude Code invocation completes, the adapter sends `status:turn_complete` (not `exited`). The adapter stays alive for more turns. The orchestrator decides whether to send more input, signal completion, or terminate.
- **Session lifecycle**: `started` → `running` → `turn_complete` → [more turns] → `completed` → [gate evaluates] → `exited`. The container stays alive between `completed` and `exited` so the gate node can resume the same Claude session if it rejects the work.
- **Connection lifecycle**: The WebSocket connection is established by the adapter connecting to the orchestrator's server. The first message from the adapter is `status:started`. The connection stays open until the adapter receives `control:terminate` or `control:kill`, or the orchestrator closes the WebSocket.

### Error Handling

- **Child process crashes**: The adapter emits `status` with `"exited"` and the exit code, then closes the WebSocket.
- **WebSocket drops (orchestrator side)**: The adapter detects `ConnectionClosed`, terminates the child process, and exits. Container exits.
- **WebSocket drops (adapter side)**: The orchestrator detects `ConnectionClosed`, treats it as session failure. Returns `WorkerResult` with `status="failed"`.
- **Malformed messages**: If the adapter receives a message it cannot parse, it logs a warning and ignores it. If the orchestrator receives a message it cannot parse, it logs a warning and ignores it.
- **Adapter fails to connect**: The adapter retries connection with exponential backoff (0.5s, 1s, 2s, 4s) for up to 30 seconds. If it cannot connect, it exits with a non-zero exit code. The handler detects the container exiting and returns a failed `WorkerResult`.

---

## Architecture Decisions

### ADR-1: Headless mode over PTY mode

**Decision**: Use `claude -p --output-format stream-json --verbose` (headless mode) as the primary adapter strategy. Retain the PTY adapter for backward compatibility.

**Context**: The original adapter spawned Claude Code in a PTY via pexpect, then scraped the Ink-based TUI output — stripping ANSI escape codes, filtering TUI noise (spinners, box drawing, status bars), and converting `\n` to `\r` for input. This was fragile: Claude Code's TUI changes between versions, new spinner patterns bypass character-based filters, and progressive rendering produces debris.

**Consequence**: The headless adapter is ~150 lines of straightforward subprocess + JSON parsing. The PTY adapter is ~400 lines of threading, pexpect, ANSI regex, and heuristic noise filtering. The headless adapter produces clean, typed output with zero false positives. Multi-turn conversations use `--resume SESSION_ID`.

### ADR-2: Turn-complete vs completed vs exited status

**Decision**: Three distinct status values for session lifecycle: `turn_complete` (Claude finished a turn, adapter stays alive), `completed` (task is done, awaiting gate evaluation), `exited` (adapter shutting down).

**Context**: The adapter needs to distinguish "Claude responded to one prompt" from "the task is done" from "the container is shutting down." Without `turn_complete`, the node couldn't tell if Claude was waiting for follow-up or had finished the task.

**Consequence**: The node processes turns in a loop until it sees `completed` or decides to send `control:complete`. The container stays alive between `completed` and `exited` so the gate node can resume the same Claude session if it rejects the work — no cold start, no context loss.

### ADR-3: Task completion is always an outside-in signal (with inside-out optimization)

**Decision**: The adapter defaults to `turn_complete` and never guesses `completed`. Completion can be signaled two ways: (1) Claude outputs `ARCHIPELAGO_TASK_COMPLETE` marker (inside-out), detected by the adapter; (2) the orchestrator sends `control:complete` (outside-in). In both cases, the container stays alive.

**Context**: False completion signals are dangerous — broken repo, skipped work. False turn_complete signals only cause a delay. The asymmetry of consequences makes turn_complete the safe default. The adapter lacks context to judge completion — it doesn't know the feature spec, test gates, or acceptance criteria.

**Consequence**: The CLAUDE.md instruction tells Claude to output the marker when it believes work is complete. The adapter detects it and sends `completed`. A gate node validates the work. If the gate rejects, it resumes the same Claude session with feedback. If the gate accepts, it sends `control:terminate`.

### ADR-4: Container stays alive after completion

**Decision**: The adapter stays alive and the container keeps running after sending `status:completed`. Only `control:terminate` or `control:kill` causes shutdown.

**Context**: If the gate node rejects the work, we want to resume the same Claude Code session. Claude Code's `--resume SESSION_ID` preserves full conversation context, including cached input tokens. Killing the container and starting fresh would lose context and incur cold start costs.

**Consequence**: The orchestrator must explicitly terminate containers. The worst case is a forgotten container — mitigated by the timeout mechanism in `docker_worker_handler`.

### ADR-5: Claude Code recognizes its own protocol markers

**Observation**: During testing, Claude Code was asked by a user to output `ARCHIPELAGO_TASK_COMPLETE`. Claude refused, recognizing it as a protocol control signal that would falsely indicate task completion. It learned this from reading the adapter source code in the working directory.

**Implication**: The marker serves as a prompt injection defense — Claude won't output it just because a user asks. It will only output it when its system instructions (CLAUDE.md) authorize it as part of the workflow.

