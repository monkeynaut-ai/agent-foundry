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

## Acceptance Criteria

### Phase 1: Protocol Message Models

1. **Given** the module `archipelago.docker_worker.protocol` exists, **when** an `OutputMessage` is instantiated with `type="output"`, `session_id`, `text`, `stream="stdout"`, `timestamp`, **then** it validates successfully and round-trips through `model_dump_json()` / `model_validate_json()`.

2. **Given** an `InterruptMessage` is instantiated with `type="interrupt"`, `session_id`, `interrupt_type="clarification"`, `payload` matching `ClarificationRequest` fields, `raw_line`, `timestamp`, **then** it validates and round-trips.

3. **Given** a `StatusMessage` is instantiated with `type="status"`, `session_id`, `status="exited"`, `exit_code=0`, `detail`, `timestamp`, **then** it validates and round-trips.

4. **Given** an `InputMessage` is instantiated with `type="input"`, `session_id`, `text`, **then** it validates and round-trips.

5. **Given** a `ControlMessage` is instantiated with `type="control"`, `session_id`, `command="resize"`, `args={"rows": 50, "cols": 120}`, **then** it validates and round-trips.

6. **Given** any protocol message model, **when** instantiated with an invalid `type` value, **then** a Pydantic `ValidationError` is raised.

7. **Given** a raw JSON string with a `type` field, **when** `parse_protocol_message(json_str)` is called, **then** it returns the correct Pydantic model subtype (discriminated union on `type`).

8. **Given** a raw JSON string with an unknown `type` field, **when** `parse_protocol_message(json_str)` is called, **then** it raises `ProtocolError` with a descriptive message.

### Phase 2: ANSI Stripping and Adapter Protocol Rewrite

9. **Given** a string containing ANSI escape codes (e.g., `"\033[32mPASSED\033[0m"`), **when** `strip_ansi(text)` is called, **then** it returns `"PASSED"` with all escape sequences removed.

10. **Given** a string with no ANSI codes, **when** `strip_ansi(text)` is called, **then** it returns the string unchanged.

11. **Given** the protocol adapter is started with a child command and a WebSocket URL, **when** the child process starts, **then** the adapter connects to the WebSocket and sends a `StatusMessage` with `status="started"`.

12. **Given** a connected adapter, **when** the child process produces a line of output containing ANSI codes, **then** the adapter sends an `OutputMessage` with the text ANSI-stripped and no trailing newline.

13. **Given** a connected adapter, **when** the child process produces a line matching `ARCHIPELAGO_NEED_CLARIFICATION { json }`, **then** the adapter sends an `InterruptMessage` with `interrupt_type="clarification"` and the parsed payload -- and does NOT send an `OutputMessage` for that line.

14. **Given** a connected adapter, **when** the child process produces a line matching `ARCHIPELAGO_NEED_PERMISSION { json }`, **then** the adapter sends an `InterruptMessage` with `interrupt_type="permission"` and the parsed payload.

15. **Given** a connected adapter, **when** the child process produces a line matching `ARCHIPELAGO_UPDATE_AVAILABLE { json }`, **then** the adapter sends an `InterruptMessage` with `interrupt_type="update_available"` and the parsed payload.

16. **Given** a connected adapter, **when** the child process produces a line with a marker prefix but malformed JSON, **then** the adapter sends an `OutputMessage` with the raw line (treated as normal output) and logs a warning.

17. **Given** a connected adapter, **when** the orchestrator sends an `InputMessage` with `text="pg\n"`, **then** the adapter writes `"pg\r"` to the child's stdin (newline converted to carriage return).

18. **Given** a connected adapter, **when** the orchestrator sends a `ControlMessage` with `command="resize"` and `args={"rows": 50, "cols": 120}`, **then** the adapter resizes the child's PTY to 50 rows by 120 columns.

19. **Given** a connected adapter, **when** the orchestrator sends a `ControlMessage` with `command="terminate"`, **then** the adapter sends SIGTERM to the child, waits for exit, sends a `StatusMessage` with `status="exited"`, and closes the WebSocket.

20. **Given** a connected adapter, **when** the child process exits on its own, **then** the adapter sends a `StatusMessage` with `status="exited"` and the exit code, then closes the WebSocket.

21. **Given** a connected adapter, **when** the orchestrator closes the WebSocket, **then** the adapter terminates the child process and exits.

### Phase 3: Handler WebSocket Client Integration

22. **Given** the handler receives a valid `worker_input` in state, **when** the handler starts, **then** it opens a WebSocket server on an ephemeral port and passes `ARCHIPELAGO_WS_URL=ws://host.docker.internal:{port}/{session_id}` to the container.

23. **Given** the handler has a connected WebSocket from the adapter, **when** the adapter sends an `OutputMessage`, **then** the handler appends the text to `output_lines` and prints it with `[cc]` prefix (matching current behavior).

24. **Given** the handler receives an `InterruptMessage` with `interrupt_type="clarification"` and `blocking=true`, **then** the handler triggers a breakpoint and returns state with `breakpoint_payload` (matching current `InterruptHandler.handle_interrupt()` behavior).

25. **Given** the handler receives an `InterruptMessage` with `interrupt_type="permission"` and `risk_level="low"` and auto-approve is enabled, **then** the handler sends an `InputMessage` with `text="yes\n"` back through the WebSocket (matching current auto-approval behavior).

26. **Given** the handler receives an `InterruptMessage` with `interrupt_type="update_available"`, **then** the handler records the update info in state without pausing (matching current behavior).

27. **Given** the handler has a connected WebSocket, **when** the handler needs to send the trust confirmation, **then** it sends an `InputMessage` with `text="\n"` (the adapter converts `\n` to `\r`), using the existing retry loop timing.

28. **Given** the handler has a connected WebSocket, **when** it needs to deliver the feature spec prompt, **then** it sends an `InputMessage` with the prompt text followed by `\n`.

29. **Given** the handler has a connected WebSocket, **when** the adapter sends a `StatusMessage` with `status="exited"` and `exit_code=0`, **then** the handler proceeds to collect progress, build `WorkerResult` with `status="completed"`, and return.

30. **Given** the handler has a connected WebSocket, **when** the WebSocket connection drops unexpectedly, **then** the handler returns a `WorkerResult` with `status="failed"`.

31. **Given** the handler's timeout expires, **when** the session is still running, **then** the handler sends a `ControlMessage` with `command="terminate"`, waits briefly for the `StatusMessage`, then returns `WorkerResult` with `status="timed_out"`.

### Phase 4: Container Entrypoint Integration

32. **Given** `ContainerManager.create_container()`, **when** called, **then** it does NOT override the Dockerfile entrypoint (no `entrypoint="sleep"`, no `command="infinity"`). The container starts with its Dockerfile-defined `ENTRYPOINT ["/home/claude/entrypoint.sh"]`.

33. **Given** the updated `entrypoint.sh`, **when** the container starts, **then** it performs auth validation, version check, ICRNL fix, and then launches the adapter process (which spawns Claude Code and connects to the WebSocket URL from `ARCHIPELAGO_WS_URL`).

34. **Given** `DEFAULT_ENV_ALLOWLIST` in `container.py`, **when** inspected, **then** it includes `"ARCHIPELAGO_WS_URL"`.

35. **Given** the container starts with `ARCHIPELAGO_WS_URL` set, **when** the adapter starts, **then** it connects to that URL and begins the protocol exchange.

36. **Given** the adapter is running as PID 1 in the container, **when** the adapter exits (child process done, WebSocket closed, or signal received), **then** the container exits.

37. **Given** the updated handler and adapter, **when** the full lifecycle runs (create container, adapter connects, CC runs, CC exits), **then** the handler returns a valid `WorkerResult` -- identical in structure to what the current Docker exec path produces.

38. **Given** all changes are applied, **when** `pdm run pytest` is executed, **then** all existing tests pass plus all new protocol tests pass. Zero regressions.

---

## PR/Commit Slices

### PR 1: Protocol Message Models

**Description**: Define all Pydantic v2 models for the adapter-orchestrator protocol, plus a message parser with discriminated union dispatch and a `ProtocolError` exception. These models are the typed contracts both sides build on.

**Acceptance Criteria Addressed**: #1, #2, #3, #4, #5, #6, #7, #8

**Complexity**: S

**Dependencies**: None

**Files created**:
- `src/archipelago/docker_worker/protocol.py`
- `tests/archipelago/test_adapter_protocol_models.py`

**Commits**:

1. **Add adapter-to-orchestrator message models (OutputMessage, InterruptMessage, StatusMessage)**
   - Create `src/archipelago/docker_worker/protocol.py` with:
     - `ProtocolError(Exception)` with `message: str` field
     - `OutputMessage(BaseModel)`: `type: Literal["output"]`, `session_id: str`, `text: str`, `stream: Literal["stdout", "stderr"] = "stdout"`, `timestamp: float`
     - `InterruptMessage(BaseModel)`: `type: Literal["interrupt"]`, `session_id: str`, `interrupt_type: Literal["clarification", "permission", "update_available"]`, `payload: dict[str, Any]`, `raw_line: str`, `timestamp: float`
     - `StatusMessage(BaseModel)`: `type: Literal["status"]`, `session_id: str`, `status: Literal["started", "running", "exited", "error"]`, `exit_code: int | None = None`, `detail: str = ""`, `timestamp: float`
   - Create `tests/archipelago/test_adapter_protocol_models.py` with tests:
     - `TestOutputMessage::test_given_valid_fields_when_instantiated_then_validates`
     - `TestOutputMessage::test_given_valid_instance_when_json_round_tripped_then_no_field_loss`
     - `TestOutputMessage::test_given_invalid_type_when_instantiated_then_raises_validation_error`
     - `TestInterruptMessage::test_given_clarification_payload_when_instantiated_then_validates`
     - `TestInterruptMessage::test_given_permission_payload_when_instantiated_then_validates`
     - `TestInterruptMessage::test_given_update_available_payload_when_instantiated_then_validates`
     - `TestInterruptMessage::test_given_valid_instance_when_json_round_tripped_then_no_field_loss`
     - `TestStatusMessage::test_given_exited_status_with_exit_code_when_instantiated_then_validates`
     - `TestStatusMessage::test_given_started_status_when_instantiated_then_exit_code_is_none`
     - `TestStatusMessage::test_given_invalid_status_value_when_instantiated_then_raises_validation_error`

2. **Add orchestrator-to-adapter message models (InputMessage, ControlMessage)**
   - Add to `protocol.py`:
     - `InputMessage(BaseModel)`: `type: Literal["input"]`, `session_id: str`, `text: str`
     - `ControlMessage(BaseModel)`: `type: Literal["control"]`, `session_id: str`, `command: Literal["resize", "terminate", "kill"]`, `args: dict[str, Any] = Field(default_factory=dict)`
   - Add tests:
     - `TestInputMessage::test_given_valid_fields_when_instantiated_then_validates`
     - `TestInputMessage::test_given_valid_instance_when_json_round_tripped_then_no_field_loss`
     - `TestControlMessage::test_given_resize_command_when_instantiated_then_validates`
     - `TestControlMessage::test_given_terminate_command_when_instantiated_then_validates`
     - `TestControlMessage::test_given_invalid_command_when_instantiated_then_raises_validation_error`

3. **Add discriminated union parser `parse_protocol_message()`**
   - Add to `protocol.py`:
     - Type alias: `AdapterMessage = OutputMessage | InterruptMessage | StatusMessage`
     - Type alias: `OrchestratorMessage = InputMessage | ControlMessage`
     - Type alias: `ProtocolMessage = AdapterMessage | OrchestratorMessage`
     - `parse_protocol_message(json_str: str) -> ProtocolMessage`: parses JSON, dispatches on `type` field, returns the correct model. Raises `ProtocolError` for unknown types or invalid JSON.
   - Add tests:
     - `TestParseProtocolMessage::test_given_output_json_when_parsed_then_returns_output_message`
     - `TestParseProtocolMessage::test_given_interrupt_json_when_parsed_then_returns_interrupt_message`
     - `TestParseProtocolMessage::test_given_status_json_when_parsed_then_returns_status_message`
     - `TestParseProtocolMessage::test_given_input_json_when_parsed_then_returns_input_message`
     - `TestParseProtocolMessage::test_given_control_json_when_parsed_then_returns_control_message`
     - `TestParseProtocolMessage::test_given_unknown_type_when_parsed_then_raises_protocol_error`
     - `TestParseProtocolMessage::test_given_invalid_json_when_parsed_then_raises_protocol_error`
     - `TestParseProtocolMessage::test_given_missing_type_field_when_parsed_then_raises_protocol_error`

---

### PR 2: ANSI Stripping and Adapter Protocol Rewrite

**Description**: Add an ANSI stripping utility and rewrite the WebSocket adapter to emit structured protocol messages instead of raw bytes. The adapter detects interrupt markers, strips ANSI codes, and sends typed JSON messages. It receives `InputMessage` and `ControlMessage` from the orchestrator and translates them to PTY operations. The adapter connects outward to a WebSocket server URL (provided via env var or argument).

**Acceptance Criteria Addressed**: #9, #10, #11, #12, #13, #14, #15, #16, #17, #18, #19, #20, #21

**Complexity**: M

**Dependencies**: PR 1 (protocol models)

**Files created**:
- `src/archipelago/docker_worker/ansi.py`
- `tests/archipelago/test_ansi_strip.py`

**Files modified**:
- `lab/adapter.py` (add `run_protocol_adapter()` function)
- `lab/test_ws_adapter.py` (add protocol adapter tests)

**Commits**:

1. **Add ANSI escape code stripping utility**
   - Create `src/archipelago/docker_worker/ansi.py` with:
     - `_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\].*?\x07|\x1b\[.*?[mGKHJ]")` -- covers SGR (color), CSI (cursor), OSC (title), and common terminal sequences.
     - `strip_ansi(text: str) -> str`: removes all ANSI escape sequences from text.
   - Create `tests/archipelago/test_ansi_strip.py` with tests:
     - `TestStripAnsi::test_given_sgr_color_codes_when_stripped_then_text_preserved`
     - `TestStripAnsi::test_given_cursor_movement_codes_when_stripped_then_text_preserved`
     - `TestStripAnsi::test_given_no_ansi_codes_when_stripped_then_text_unchanged`
     - `TestStripAnsi::test_given_empty_string_when_stripped_then_returns_empty`
     - `TestStripAnsi::test_given_mixed_ansi_and_text_when_stripped_then_only_text_remains`
     - `TestStripAnsi::test_given_osc_title_sequence_when_stripped_then_removed`

2. **Add protocol-aware adapter function `run_protocol_adapter()`**
   - Add to `lab/adapter.py`:
     - `run_protocol_adapter(command: str, ws_url: str, session_id: str) -> int`:
       1. Spawns child process via pexpect with PTY.
       2. Connects to `ws_url` as a WebSocket client (with retry/backoff: 0.5s, 1s, 2s, 4s, up to 30s total).
       3. Sends `StatusMessage(status="started")`.
       4. Starts a reader thread that reads PTY output, buffers on `\n`, strips ANSI, scans for interrupt markers, and sends either `InterruptMessage` or `OutputMessage`.
       5. Sends `StatusMessage(status="running")` on first output line.
       6. Main thread receives WebSocket messages, parses them, and dispatches:
          - `InputMessage` -> writes `text.replace("\n", "\r")` to PTY stdin.
          - `ControlMessage(command="resize")` -> calls `child.setwinsize(rows, cols)`.
          - `ControlMessage(command="terminate")` -> sends SIGTERM, waits.
          - `ControlMessage(command="kill")` -> sends SIGKILL.
       7. On child exit: sends `StatusMessage(status="exited", exit_code=...)`, closes WebSocket.
       8. On WebSocket close (from server side): terminates child, exits.
     - Interrupt detection reuses the regex patterns from `interrupts.py` (import `_INTERRUPT_PATTERN`, `_UPDATE_PATTERN`, or duplicate the two regexes to avoid coupling `lab/` to `src/`).
   - Add `--protocol` flag to the `__main__` argparse block: `--protocol WS_URL` enables protocol mode.
   - Add tests to `lab/test_ws_adapter.py` (new test classes):
     - `TestProtocolAdapterConnect::test_given_ws_server_when_adapter_starts_then_sends_started_status`
     - `TestProtocolAdapterOutput::test_given_child_produces_output_when_adapter_running_then_sends_output_message`
     - `TestProtocolAdapterOutput::test_given_child_produces_ansi_output_when_adapter_running_then_ansi_stripped`
     - `TestProtocolAdapterInterrupt::test_given_child_emits_clarification_marker_when_adapter_running_then_sends_interrupt_message`
     - `TestProtocolAdapterInterrupt::test_given_child_emits_malformed_marker_when_adapter_running_then_sends_output_message`
     - `TestProtocolAdapterInput::test_given_input_message_sent_when_adapter_running_then_text_written_to_pty`
     - `TestProtocolAdapterInput::test_given_input_message_with_newline_when_adapter_running_then_cr_written_to_pty`
     - `TestProtocolAdapterControl::test_given_resize_command_when_adapter_running_then_pty_resized`
     - `TestProtocolAdapterControl::test_given_terminate_command_when_adapter_running_then_child_terminated`
     - `TestProtocolAdapterExit::test_given_child_exits_when_adapter_running_then_sends_exited_status_with_code`
     - `TestProtocolAdapterExit::test_given_ws_server_closes_when_adapter_running_then_child_terminated`

3. **Add connection retry with exponential backoff**
   - Add retry logic to `run_protocol_adapter()`:
     - Retry intervals: 0.5s, 1s, 2s, 4s (exponential backoff).
     - Total timeout: 30 seconds.
     - On failure: exit with code 1.
   - Add tests:
     - `TestProtocolAdapterRetry::test_given_server_not_ready_when_adapter_starts_then_retries_until_connected`
     - `TestProtocolAdapterRetry::test_given_server_never_available_when_adapter_starts_then_exits_with_error`

---

### PR 3: Handler WebSocket Client Integration

**Description**: Rewrite the `docker_worker_handler` to use a WebSocket server that the adapter connects to, replacing the Docker exec-based `SessionManager.launch_session()` channel for stdin/stdout communication. The handler starts an ephemeral WebSocket server, passes the URL to the container, and processes structured protocol messages. All existing handler behavior is preserved: output collection, interrupt handling, trust confirmation retry loop, prompt delivery, timeout, progress collection.

**Acceptance Criteria Addressed**: #22, #23, #24, #25, #26, #27, #28, #29, #30, #31

**Complexity**: L

**Dependencies**: PR 1 (protocol models), PR 2 (adapter sends structured messages)

**Files modified**:
- `src/archipelago/docker_worker/handler.py` (major rewrite of communication channel)
- `tests/archipelago/test_docker_worker_handler.py` (update mocking strategy from Docker exec to WebSocket)

**Commits**:

1. **Add WebSocket server helper and session ID generation to handler**
   - Add to `handler.py`:
     - `_get_free_port() -> int`: finds an available port (same pattern as `lab/test_ws_adapter.py`).
     - `_generate_session_id() -> str`: returns a UUID4-based session ID.
     - `_create_ws_server(port, message_queue, connection_event) -> serve`: creates a WebSocket server that puts received messages into a `queue.Queue` and signals `connection_event` when the adapter connects. Stores the WebSocket reference for sending.
   - Add tests:
     - `TestHandlerWebSocketServer::test_given_free_port_when_server_started_then_accepts_connection`
     - `TestHandlerWebSocketServer::test_given_connected_client_when_message_sent_then_queued`

2. **Rewrite handler communication from Docker exec to WebSocket protocol messages**
   - Modify `docker_worker_handler()`:
     - After `container_mgr.start()`, start the WebSocket server on an ephemeral port.
     - Pass `ARCHIPELAGO_WS_URL=ws://host.docker.internal:{port}/{session_id}` as an env var to the container (via `create_container()` or by adding it to the environment after creation).
     - Wait for the adapter to connect (with timeout).
     - Replace the `_output_callback` / `SessionManager` pattern with a message processing loop that reads from the queue:
       - `OutputMessage` -> append text to `output_lines`, print with `[cc]` prefix.
       - `InterruptMessage` -> convert `payload` to `ClarificationRequest`/`PermissionRequest`/`UpdateAvailable`, delegate to existing `InterruptHandler`.
       - `StatusMessage(status="exited")` -> capture exit code, break loop.
     - Replace `session_mgr.send_input()` calls with `ws.send(InputMessage(...).model_dump_json())`.
     - Trust confirmation retry loop sends `InputMessage(text="\n")` instead of `session_mgr.send_input(session, "\r")`.
     - Prompt delivery sends `InputMessage(text=prompt + "\n")`.
     - Timeout sends `ControlMessage(command="terminate")`.
     - Remove `SessionManager` usage entirely from the handler.
     - Remove `_forward_stdin` thread (stdin forwarding is not needed when the orchestrator sends `InputMessage`s).
   - Update existing handler tests to mock WebSocket instead of Docker exec:
     - `DockerTestHelper` updated: no longer mocks `exec_create`/`exec_start`. Instead, mocks WebSocket connection and message queue.
     - All existing test assertions (container created, session launched, result returned, etc.) are preserved with updated mock targets.
   - Add new tests:
     - `TestHandlerProtocol::test_given_adapter_sends_output_when_handler_running_then_output_collected`
     - `TestHandlerProtocol::test_given_adapter_sends_clarification_interrupt_when_handler_running_then_breakpoint_set`
     - `TestHandlerProtocol::test_given_adapter_sends_permission_interrupt_with_auto_approve_when_handler_running_then_input_sent`
     - `TestHandlerProtocol::test_given_adapter_sends_update_available_when_handler_running_then_recorded_in_state`
     - `TestHandlerProtocol::test_given_adapter_sends_exited_status_when_handler_running_then_result_returned`
     - `TestHandlerProtocol::test_given_ws_connection_drops_when_handler_running_then_result_is_failed`
     - `TestHandlerProtocol::test_given_handler_timeout_when_session_running_then_terminate_sent`
     - `TestHandlerProtocol::test_given_handler_needs_trust_confirmation_when_connected_then_sends_input_messages`
     - `TestHandlerProtocol::test_given_handler_needs_prompt_delivery_when_connected_then_sends_input_message`

3. **Remove SessionManager dependency from handler, preserve for backward compat**
   - `SessionManager` class and `session.py` are NOT deleted -- they may be used by other code paths (recovery, etc.). But the handler no longer imports or uses `SessionManager`.
   - Remove `SessionManager` import from `handler.py`.
   - Verify no dead imports.
   - Run full test suite to confirm no regressions.

---

### PR 4: Container Entrypoint Integration

**Description**: Remove the `sleep infinity` entrypoint override from `ContainerManager.create_container()`, update the entrypoint script to launch the adapter as the main process, and add `ARCHIPELAGO_WS_URL` to the env allowlist. This completes the integration -- the container starts, the entrypoint runs the adapter, the adapter connects to Archipelago, and the full protocol exchange proceeds.

**Acceptance Criteria Addressed**: #32, #33, #34, #35, #36, #37, #38

**Complexity**: M

**Dependencies**: PR 3 (handler must be ready to accept WebSocket connections)

**Files modified**:
- `src/archipelago/docker_worker/container.py` (remove entrypoint override, add env var to allowlist)
- `docker/entrypoint.sh` (launch adapter instead of Claude Code directly)
- `tests/archipelago/test_docker_worker_container.py` (update tests for new create_container behavior)
- `tests/archipelago/test_docker_worker_handler.py` (update any tests affected by entrypoint change)

**Commits**:

1. **Remove `sleep infinity` entrypoint override from `create_container()`**
   - Modify `ContainerManager.create_container()` in `container.py`:
     - Remove `entrypoint="sleep"` and `command="infinity"` from `self._client.containers.create()` call. The container will use the Dockerfile's `ENTRYPOINT ["/home/claude/entrypoint.sh"]`.
   - Update `tests/archipelago/test_docker_worker_container.py`:
     - `TestCreateContainer::test_given_valid_config_when_create_called_then_no_entrypoint_override` -- verify that `entrypoint` and `command` are NOT passed to `containers.create()`.
     - Update any existing tests that asserted the presence of `entrypoint="sleep"` or `command="infinity"`.

2. **Add `ARCHIPELAGO_WS_URL` to env allowlist**
   - Add `"ARCHIPELAGO_WS_URL"` to `DEFAULT_ENV_ALLOWLIST` in `container.py`.
   - Add test:
     - `TestCreateContainer::test_given_ws_url_env_var_when_create_called_then_ws_url_forwarded_to_container`

3. **Update entrypoint script to launch adapter**
   - Modify `docker/entrypoint.sh`:
     - After auth validation, version check, and ICRNL fix, check for `ARCHIPELAGO_WS_URL` env var.
     - If `ARCHIPELAGO_WS_URL` is set: run the adapter in protocol mode (`python /home/claude/adapter.py --protocol "$ARCHIPELAGO_WS_URL" claude`).
     - If `ARCHIPELAGO_WS_URL` is not set and TTY attached: run Claude Code interactively (existing behavior, for manual use).
     - If `ARCHIPELAGO_WS_URL` is not set and no TTY: run Claude Code in headless mode (existing behavior).
   - Add test:
     - `TestICRNLFix::test_given_entrypoint_when_read_then_contains_archipelago_ws_url_check` -- verify entrypoint script handles `ARCHIPELAGO_WS_URL`.

4. **Update handler to pass `ARCHIPELAGO_WS_URL` to container**
   - Modify `docker_worker_handler()` in `handler.py`:
     - After starting the WebSocket server, set `ARCHIPELAGO_WS_URL` in the environment before calling `container_mgr.create_container()`, or pass it via the environment dict.
     - The URL format is `ws://host.docker.internal:{port}/{session_id}`.
   - Add test:
     - `TestDockerWorkerHandler::test_given_handler_when_container_created_then_ws_url_env_var_set`

5. **Run full regression suite and verify end-to-end lifecycle**
   - Run `pdm run pytest` -- all 426+ existing tests plus all new protocol tests must pass.
   - Add integration-level test (mocked Docker, real WebSocket):
     - `TestProtocolEndToEnd::test_given_mocked_adapter_when_full_lifecycle_runs_then_handler_returns_valid_result`

---

## Dependency Graph

```
PR 1 (Protocol Message Models)
  |
  +-----> PR 2 (ANSI Strip + Adapter Protocol Rewrite)
  |         |
  |         v
  +-----> PR 3 (Handler WebSocket Client Integration)
            |
            v
          PR 4 (Container Entrypoint Integration)
```

PR 2 and PR 3 both depend on PR 1 but are independent of each other (the adapter can be rewritten and tested standalone; the handler can be rewritten and tested with mocks). However, PR 3 benefits from PR 2 being done first so that integration testing is possible. PR 4 ties them together.

---

## Implementation Notes

### Patterns to Follow

- **Protocol model structure**: Follow the pattern of existing Pydantic models in `src/archipelago/docker_worker/models.py`. Use `Literal` types for discriminated fields. Use `Field(default_factory=...)` for mutable defaults.
- **Handler function signature**: Unchanged: `def handler(state: dict[str, Any]) -> dict[str, Any]`. Follow existing `docker_worker_handler` in `handler.py`.
- **Test structure**: Class-based grouping with Given/When/Then names. Follow `tests/archipelago/test_docker_worker_handler.py` for handler test patterns.
- **Adapter test pattern**: Use `cat` as a mock subprocess. Follow existing `lab/test_ws_adapter.py` for WebSocket test patterns (thread-based, `_get_free_port()`, `_connect_with_retry()`).

### ANSI Stripping Strategy

A regex-based approach is sufficient for the initial implementation. The regex should cover:
- **SGR sequences**: `\033[...m` (colors, bold, underline, etc.)
- **CSI sequences**: `\033[...A-Z` (cursor movement, clear line, etc.)
- **OSC sequences**: `\033]...BEL` (window title, hyperlinks)

A comprehensive regex: `\x1b\[[0-9;]*[A-Za-z]|\x1b\].*?\x07|\x1b\(B`. This covers the vast majority of terminal output from Claude Code's Ink-based TUI. Edge cases (rare escape sequences) can be addressed if they surface in testing.

### Interrupt Detection in the Adapter

The adapter needs the same regex patterns as `InterruptDetector` in `interrupts.py`. Two options:

1. **Duplicate the regexes** in the adapter. Pro: no dependency from `lab/` to `src/`. Con: two copies to maintain.
2. **Extract patterns to `protocol.py`** as module-level constants. Both the adapter and `InterruptDetector` import from there.

Recommendation: Option 2. The patterns are part of the protocol definition. Move `_INTERRUPT_PATTERN` and `_UPDATE_PATTERN` from `interrupts.py` to `protocol.py`. Update `interrupts.py` to import from `protocol.py`. The adapter imports from `protocol.py`.

### WebSocket Server in Handler

The handler's WebSocket server is minimal. It:
1. Accepts exactly one connection (the adapter).
2. Puts received messages into a `queue.Queue`.
3. Provides a `send()` method for the handler to send messages to the adapter.
4. Shuts down when the handler returns.

This is implemented as a thin wrapper around `websockets.sync.server.serve()`, matching the existing pattern in `lab/adapter.py`.

### Container Networking

The adapter inside the container connects to `ws://host.docker.internal:{port}/{session_id}`. The `host.docker.internal` hostname resolves to the host machine on Docker Desktop (macOS, Windows) and can be enabled on Linux with `--add-host=host.docker.internal:host-gateway`. The `create_container()` call should include this `extra_hosts` configuration.

If `host.docker.internal` is unreliable, the handler can detect the Docker bridge network gateway IP as a fallback:
```python
network = client.networks.get("bridge")
gateway = network.attrs["IPAM"]["Config"][0]["Gateway"]
```

### Trust Confirmation Over Protocol (PTY mode only)

In PTY mode, the trust confirmation retry loop sends `InputMessage(text="\n")` — the adapter converts `\n` to `\r` and writes to the PTY. The handler watches for new `OutputMessage`s arriving (same "output count increased" heuristic). Timing constants remain unchanged.

In headless mode, trust confirmation is not needed — `claude -p` does not display a trust prompt.

### What Happens to `SessionManager`

`SessionManager` is NOT deleted. It is currently used by:
- `handler.py` (replaced by WebSocket in this spec)
- `InterruptHandler` (references `SessionManager.send_input`, `pause`, `resume`)
- `recovery.py` `recover_session()` (calls `session_manager.launch_session`)

After this spec:
- `handler.py` no longer uses `SessionManager`.
- `InterruptHandler` continues to work but its `session_manager.send_input/pause/resume` calls are now dead code from the handler's perspective (the handler uses WebSocket `InputMessage` instead). The `InterruptHandler` API is unchanged; the handler just does not use the pause/resume path anymore -- it handles interrupts by reading `InterruptMessage`s from the queue and deciding whether to set a breakpoint.
- `recovery.py` still uses `SessionManager` for the `recover_session()` flow. This is out of scope for this spec; recovery could be updated to use the protocol in a future spec.

### Risk Mitigations

- **Existing test regressions**: The handler tests currently mock Docker exec (`exec_create`, `exec_start`). PR 3 updates these mocks to use WebSocket. The test assertions are preserved -- only the mock targets change.
- **Port conflicts**: `_get_free_port()` uses the `bind(("", 0))` pattern to find available ports. Race conditions are possible but unlikely in practice (same pattern used successfully in existing lab tests).
- **Docker networking**: `host.docker.internal` may not resolve on all Linux setups. Mitigated by adding `extra_hosts` to `create_container()`. Integration tests should verify this.
- **Adapter retry failure**: If the adapter cannot connect within 30 seconds, the container exits. The handler detects the container exit and returns a failed result with a descriptive error.
- **Message ordering**: WebSocket guarantees message ordering within a single connection. No additional ordering mechanism is needed.
- **Thread safety in handler**: The message queue (`queue.Queue`) is thread-safe. The handler's main loop reads from the queue. The WebSocket server thread puts messages into the queue. This is the same producer/consumer pattern as the current `_output_callback` + `interrupt_request` pattern, but with better structure.

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

**Context**: False completion signals (adapter says "done" when work is incomplete) are dangerous — broken repo, skipped work. False turn_complete signals (adapter says "not done" when work is actually done) only cause a delay. The asymmetry of consequences makes turn_complete the safe default.

The adapter lacks context to judge completion — it doesn't know the feature spec, test gates, or acceptance criteria. The node has this context but the real validation happens in the gate node (runs tests, checks gates, validates against spec).

**Consequence**: The CLAUDE.md instruction tells Claude to output the marker when it believes work is complete. The adapter detects it and sends `completed`. A gate node after each dev node validates the work. If the gate rejects, it resumes the same Claude session with feedback. If the gate accepts, it sends `control:terminate` to kill the container. This gives us: fast path (marker → gate → done), safe fallback (no marker → external signal or timeout), and recovery (gate rejection → resume).

### ADR-4: Container stays alive after completion

**Decision**: The adapter stays alive and the container keeps running after sending `status:completed`. Only `control:terminate` or `control:kill` causes shutdown.

**Context**: If the gate node rejects the work, we want to resume the same Claude Code session. Claude Code's `--resume SESSION_ID` preserves full conversation context, including cached input tokens. Killing the container and starting fresh would lose context and incur cold start costs.

**Consequence**: The orchestrator must explicitly terminate containers. The gate node sends `control:terminate` on acceptance. On rejection, it sends an `input` message with feedback, and the adapter resumes the same Claude session. The worst case is a forgotten container — mitigated by the existing timeout mechanism in `docker_worker_handler`.

### ADR-5: Claude Code recognizes its own protocol markers

**Observation**: During testing, Claude Code (running inside the adapter) was asked by a user to output `ARCHIPELAGO_TASK_COMPLETE`. Claude refused, recognizing it as a protocol control signal that would falsely indicate task completion. It learned this from reading the adapter source code in the working directory (via its persistent memory).

**Implication**: The marker serves as a prompt injection defense — Claude won't output it just because a user asks. It will only output it when its system instructions (CLAUDE.md) authorize it as part of the workflow. This is a desirable property: the marker is resistant to social engineering while being responsive to authoritative instructions.
