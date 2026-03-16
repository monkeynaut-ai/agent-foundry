# Docker Worker Requirements

System requirements for the Claude Code Docker Worker — the component that delegates feature implementation to Claude Code running inside ephemeral Docker containers.

---

## 1. Capability Interface

The docker worker exposes a typed I/O contract validated at runtime.

**WorkerInput** fields:
- `repo_ref` — repository reference (branch, tag, or SHA) to check out
- `feature_spec` — structured feature specification describing the work
- `constraints` — resource and policy constraints (timeout, cost ceiling, allowed commands, network policy)
- `test_commands` — commands the worker must run to verify correctness
- `gates` — quality gates that must pass before the work is considered complete

**WorkerResult** fields:
- `result_summary` — human-readable summary of what was accomplished
- `workspace_ref` — reference to the workspace volume containing artifacts
- `patches` — list of patches/PRs produced (branch, files changed, diff summary)
- `evidence` — per-commit test evidence (commands run, pass/fail counts, output)
- `status` — terminal status: `completed`, `failed`, `interrupted`, or `timed_out`

All structures are Pydantic v2 models that round-trip through JSON serialization.

---

## 2. Container Lifecycle

Each invocation runs in a dedicated, ephemeral Docker container.

- **Provisioning**: Create a container from the worker image with the target repo checked out at `repo_ref` inside a workspace volume.
- **Streaming**: stdout/stderr stream to the orchestrator in real time for log capture and trace correlation. Each line is tagged with a monotonic timestamp and container ID.
- **Teardown**: The container is destroyed on completion, timeout, or unrecoverable error. Named workspace volumes are retained; anonymous volumes are removed.
- **Container management**: Uses Docker SDK for Python — no shell-out to the `docker` CLI.

---

## 3. Safety Baseline

The container enforces a defense-in-depth security posture. `ContainerManager.create_container()` is the single enforcement point.

- **Non-root execution**: Container runs as an unprivileged user (UID 1000).
- **Capability drop**: All Linux capabilities dropped (`cap_drop=["ALL"]`).
- **Read-only filesystem**: Base filesystem is read-only; only the workspace bind mount and `/tmp` (tmpfs, size-capped) are writable.
- **Resource limits**: CPU quota, memory limit, and PID limit are set from `WorkerConstraints`.
- **Environment filtering**: Only variables on an explicit allowlist are passed into the container.
- **No host mounts**: No sensitive host filesystem paths are mounted. The only bind mount is the workspace volume.

---

## 4. Interrupt Protocol

The worker detects structured interrupt markers in Claude Code's output and converts them to orchestrator breakpoints.

**Marker format** (emitted as single stdout lines):
```
ARCHIPELAGO_NEED_CLARIFICATION { json_payload }
ARCHIPELAGO_NEED_PERMISSION { json_payload }
```

**ClarificationRequest** fields: `question`, `options`, `default`, `blocking`.

**PermissionRequest** fields: `action`, `risk_level` (low/medium/high), `why_needed`, `alternatives`.

**Behavior**:
- Blocking clarification requests and high-risk permission requests always trigger an orchestrator breakpoint. The session is paused and the request is surfaced to the human.
- Low-risk permission requests may be auto-approved when enabled in `WorkerConstraints`, without triggering a breakpoint.
- Malformed payloads are logged as warnings and treated as normal output.
- After a human responds, the response is sent to the session and streaming resumes.

For protocol message types and the adapter communication layer, see [`adapter_protocol_spec.md`](adapter_protocol_spec.md).

---

## 5. Progress Reporting

Claude Code writes structured progress checkpoints to `progress.jsonl` in the workspace.

**Event schema** (`ProgressEvent`):
- `type` — one of: `commit_started`, `commit_green`, `pr_completed`, `blocked`
- `pr_id`, `commit_id` — identify the unit of work
- `files_changed`, `tests_added`, `tests_run` — artifact metadata
- `status`, `notes`, `timestamp`

Events are written in chronological order. The parser skips malformed lines with a warning rather than failing the entire parse.

---

## 6. Crash Recovery

If a session dies (crash, eviction, timeout), the orchestrator restores into a fresh container and resumes from the last checkpoint boundary.

**Persistence** (before recovery):
- Workspace git state: commit SHA and working-tree diff
- Progress events from `progress.jsonl`
- Claude Code transcript or run summary (if available)

**Resume logic**:
- Parse `progress.jsonl` to determine the last incomplete PR/commit boundary.
- Create a fresh container with the same workspace volume re-mounted.
- Launch Claude Code with context from the last checkpoint so it resumes at the correct boundary and does not re-execute previously completed commits.

---

## 7. Handler Integration

The docker worker is wired into the Archipelago pipeline as a standard capability handler.

- **Handler signature**: `def handler(state: dict) -> dict` — takes full pipeline state, returns merged state. The handler wraps the entire container lifecycle (create, start, stream, collect progress, handle interrupts, tear down) behind this interface.
- **Capability registry**: Registered as `coding.implement_feature_from_spec` with tags `archipelago` and `docker-worker`.
- **Pipeline integration**: The handler is resolved by `compile_plan()` and produces tracing spans for container lifecycle events.
- **Cleanup guarantee**: Container destruction runs in a finally block to prevent resource leaks.
