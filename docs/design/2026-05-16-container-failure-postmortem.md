# Container failure postmortem — capture, retain, resume

**Date:** 2026-05-16
**Status:** Design approved 2026-05-16, not yet implemented

## Goal

When an agent's container fails, leave behind enough on-disk evidence — and
optionally the live container itself — that the failure can be diagnosed
without re-running the system. Today the run dies, an error is printed to the
terminal, the containers are destroyed, and the only on-disk record is
`container.log` plus the merged `CLAUDE.md`. The 2026-05-15 OOM investigation
spent significant effort reproducing state that should have been captured
on the original failure (cgroup `memory.events`, `docker inspect`'s
`OOMKilled` flag, the failed turn's `stream.jsonl`).

## Scope

**In scope (v1):**

- **(a)** Opt-in retention of the failed container at run teardown (a config
  flag — default off — that skips the failed container's destroy so a
  developer can `docker exec` in and inspect state).
- **(b)** Always-on capture of additional postmortem artifacts to disk:
  `docker inspect`, cgroup memory snapshot, the failed turn's
  `stream.jsonl`, and (when the container is retained) an auto-generated
  `inspect-container.sh` helper.
- **(b')** Enrich the `agent_invocation_failed` lifecycle event payload
  with the most common forensic fields (`oom_killed`, `exit_code`,
  `memory_peak_bytes`) so common cases are a one-field lookup.

**Out of scope (v1, deferred):**

- **(c)** Restart / resume. The lifecycle stream + retained workspace volume
  already preserve the state needed for resume, but the orchestration command
  (`archipelago resume <run-id> --from <agent>:<invocation>`) is its own
  design. Worth doing once the postmortem patterns from (a)+(b) tell us what
  resume actually needs.
- General "checkpoint every turn" mechanics. Postmortem-only for v1.
- Automatic cleanup of retained containers (manual `docker rm -f <id>` for
  now; pairs naturally with the workspace-volume cleanup policy in task #13).

## Background — what we have today

Source: `agent-foundry/src/agent_foundry/orchestration/container_executor.py`
and `runner.py`.

**Current failure path:**

1. `container_executor._do_exec` catches `exit_code != 0` and raises
   `RuntimeError` containing the stdout/stderr blob plus the last 80 lines
   of container logs (this is the 215 KB `reason` field on
   `agent_invocation_failed`).
2. `_run` writes the `agent_invocation_failed` lifecycle event with that
   reason, then re-raises as `AgentFailedError`.
3. `_snapshot_container_artifacts` runs unconditionally in a `finally`
   block — writes `<run>/<agent>/container.log` and
   `<run>/<agent>/CLAUDE.md` to disk.
4. `runner._run_with_lifecycle`'s `finally` calls
   `registry.shutdown_all()` — every container is stopped and destroyed.

**What's on disk after a failure today:**

- ✅ `lifecycle.jsonl` with `agent_invocation_failed` event (stdout +
  ~80 log lines mashed into the `reason` string)
- ✅ `<run>/<agent>/container.log`
- ✅ `<run>/<agent>/CLAUDE.md`
- ✅ Workspace volume retained (separate from container lifecycle —
  `archipelago-ws-<feature>-<ts>`)
- ✅ Auto-generated `inspect-workspace.sh` script

**What's not on disk:**

- ❌ `docker inspect` output (no `OOMKilled`, `ExitCode`, `State`,
  `RestartCount`, `OOMScoreAdj`, `HostConfig.Memory`, …)
- ❌ Any cgroup memory state (`memory.events`, `memory.peak`,
  `memory.current`, `memory.max`)
- ❌ The failed turn's `stream.jsonl` (turn-level files only land on
  successful turns; on failure the raw output is base64-style mashed
  into the lifecycle event's `reason` field)
- ❌ The container itself (destroyed in `shutdown_all`)

## Is keeping the container helpful?

Depends on the failure mode:

- **Container died externally (SIGKILL / OOM-kill / docker stop).**
  Process is dead. You cannot `docker exec` in. But `docker inspect` still
  works and yields `OOMKilled`, `ExitCode`, `State.Status`, etc. For this
  class, the win comes from **capturing the inspect output**, not from
  keeping the container alive.
- **Agent emitted `failed` / `clarification_needed` but the container is
  alive.** `docker exec` works. You can read `/proc/*/status`,
  `/sys/fs/cgroup/memory.events`, `/tmp/...`, look at what processes were
  running, inspect the workspace mount as-the-agent-saw-it. Here, **keeping
  the container is genuinely valuable**.

Both have value, and they target different failure shapes. (a) handles the
second; (b) handles the first.

## Design

### (a) Opt-in retention of the failed container

Add `pause_on_failure: bool` to `RunContext`, default `False`. Env-var
override (`AGENT_FOUNDRY_PAUSE_ON_FAILURE=1`) for ad-hoc forensic runs that
don't touch code.

When `True`:

- `registry.shutdown_all` excludes the failed container from its destroy
  list. Successful containers in the same run still destroy normally — we
  retain only what's needed for the postmortem.
- On run exit, the runner logs a structured message:
  *"Container `<id>` (agent: `<name>`, invocation: `<N>`) retained for
  inspection. Clean up: `docker rm -f <id>`."*
- The auto-generated `inspect-container.sh` (see (b)) gives the developer a
  ready-to-run shell into the container.

When `False` (default): current behavior. Production runs don't accumulate
dead containers.

### (b) Always-on postmortem snapshot

Extend `_snapshot_container_artifacts` (which already runs in `finally`):

| Artifact | Source | Purpose |
|---|---|---|
| `<run>/<agent>/docker-inspect.json` | `manager.inspect(handle)` | `OOMKilled`, `ExitCode`, `State`, `Mounts`, `Config`, `HostConfig.Memory` |
| `<run>/<agent>/cgroup-memory.txt` | `docker exec ... cat /sys/fs/cgroup/memory.{events,peak,current,max}` | Memory peak, OOM event count |
| `<run>/<agent>/turns/<N>/stream.jsonl` (failed turns) | The raw output bytes returned from `_do_exec` | Stop parsing JSON streams out of the 215 KB `reason` blob |
| `<run>/<agent>/inspect-container.sh` (only if retained) | Auto-generated | `docker exec -it <id> bash` with the right user/groups |

Captured for **every** invocation, not just failed ones — they're cheap, and
having the success baseline for comparison was repeatedly useful in the
OOM investigation.

### (b') Enriched lifecycle event payload

Today: `agent_invocation_failed` has a single 215 KB `reason` string.

Proposed: add structured fields alongside it.

```jsonc
{
  "type": "agent_invocation_failed",
  "agent_name": "implementer",
  "invocation": 1,
  "exit_code": 137,
  "oom_killed": true,
  "memory_peak_bytes": 3221229568,
  "memory_max_bytes": 3221225472,
  "reason": "claude exec failed (exit=137)..."
}
```

The structured fields make common failure-mode dispatch a one-line check
(`if event.oom_killed`). The `reason` stays for the long tail of
"something weird happened, read the blob."

These fields are populated from the same sources as (b) — `docker inspect`
and the cgroup memory files. If the inspect/cgroup reads fail (best-effort,
inside the `finally`), the fields are absent or `null` rather than
blocking the event from being written.

### Container manager abstraction

Today, `ContainerManagerBase` exposes `start`, `stop`, `destroy`, `exec_run`,
`read_logs`, `read_file_from_container`, `write_file_to_container`. It does
*not* expose `inspect` or a generic cgroup-file read.

Options:

1. **Extend the abstraction.** Add `inspect(handle) -> dict` and
   `read_cgroup(handle, key) -> str` (or fold the cgroup read into the
   existing `read_file_from_container` with path `/sys/fs/cgroup/...`).
   Cleaner — keeps the docker SDK encapsulated, lets `FakeContainerManager`
   stub things for tests.
2. **Side-channel via direct `docker` CLI.** Skip the abstraction; just
   `subprocess.run(["docker", "inspect", container_id])`. Simpler but
   couples the postmortem path to the host's docker CLI.

Recommend option 1. The cost is two new abstract methods + matching
implementations in `DockerContainerManager` and `FakeContainerManager`,
both small.

## Tests (TDD-shaped)

1. `test_postmortem_snapshots_docker_inspect_on_success` — even healthy
   invocations capture `docker-inspect.json` with `ExitCode: 0`.
2. `test_postmortem_snapshots_cgroup_memory` — `cgroup-memory.txt` exists,
   contains the expected keys.
3. `test_failed_turn_persists_stream_jsonl` — when a turn fails, raw output
   lands in `turns/<N>/stream.jsonl` (today this only happens on successful
   turns).
4. `test_agent_invocation_failed_event_enriched` — payload includes
   `oom_killed`, `exit_code`, `memory_peak_bytes` when the inspect/cgroup
   reads succeed.
5. `test_agent_invocation_failed_event_omits_fields_on_inspect_failure` —
   if the manager raises while reading inspect/cgroup, the structured
   fields are absent but the event still writes (and `reason` is still
   present).
6. `test_pause_on_failure_retains_failed_container` — with
   `pause_on_failure=True`, `shutdown_all` skips the failed container's
   destroy.
7. `test_pause_on_failure_still_destroys_other_containers` — successful
   containers in the same run still destroy.
8. `test_pause_on_failure_writes_inspect_script` — auto-generates
   `inspect-container.sh` when a container is retained.
9. `test_pause_on_failure_env_override` — env var
   `AGENT_FOUNDRY_PAUSE_ON_FAILURE=1` flips the default without changing
   the `RunContext` argument.

## Decisions (resolved 2026-05-16)

- **Default for `pause_on_failure`: `False`.** Opt-in only. Production runs
  don't accumulate dead containers; forensic runs explicitly enable.
- **Retention scope: per-run.** One flag per `RunContext`; every container
  in the run honors the same setting. Per-agent retention deferred until
  someone asks for it.
- **Disk pressure: acceptable.** A `docker inspect` JSON is ~5–20 KB;
  across all invocations in a run that's MB-scale, not a concern.
- **Stream-JSONL on failure: persist the full raw_output to
  `turns/<N>/stream.jsonl`.** Cap the write at 50 MB per turn (anything
  larger is pathological and indicates a different bug to investigate).
- **Cgroup snapshot: point-in-time at teardown.** `memory.peak` is
  cumulative max-since-boot so it already captures the peak; the
  `memory.events` counters are cumulative too. Periodic mid-run sampling
  is a separate observability ticket if/when we want the climb-rate
  pattern. Out of scope here.
- **Cgroup-v1 hosts: not supported.** Production hosts are v2; v1
  fallback is out of scope and won't be added as a hypothetical.

## Opt-in surface

Agent-foundry ships two entry points for `pause_on_failure`:

- **Programmatic (Python):** `RunContext(pause_on_failure=True, ...)`.
  Used by tests and library callers.
- **Env var:** `AGENT_FOUNDRY_PAUSE_ON_FAILURE=1` consumed by the
  `RunContext` default factory. Used for ad-hoc shell-driven forensic
  runs that don't touch code.

A CLI flag (e.g. `archipelago run --pause-on-failure`) is archipelago's
call to make on its own CLI surface, tracked separately if/when needed.

## Implementation order

If approved, ship in this order so each step is testable on its own:

1. Extend `ContainerManagerBase` with `inspect` and `read_cgroup` (or
   reuse `read_file_from_container` for cgroup paths). Implement on both
   the docker and fake managers. Tests: shape only.
2. Extend `_snapshot_container_artifacts` to write `docker-inspect.json`
   and `cgroup-memory.txt`. Tests 1–2.
3. Persist failed-turn `stream.jsonl` (today raw_output is discarded when
   the failure path raises). Test 3.
4. Enrich `agent_invocation_failed` payload. Tests 4–5.
5. Add `pause_on_failure` plumbing + env override. Tests 6–9.
6. Auto-generate `inspect-container.sh`. Test 8.
