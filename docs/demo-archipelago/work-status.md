# Demo-Archipelago Work Status

## Completed

1. **Create worker CLAUDE.md** — `docker/CLAUDE.md` baked into image at `/home/claude/.claude/CLAUDE.md`. Covers role, task completion marker, interrupt markers, working style. Skipped progress.jsonl instructions (see backlog item 15 to investigate).
2. **Replace stale adapter in image** — Dockerfile now copies `src/archipelago/docker_worker/headless_adapter.py` (build context must be project root: `docker build -f docker/Dockerfile .`). Entrypoint updated: removed `stty -icrnl` (PTY-only dead code), adapter invoked without initial prompt. `_map_event_to_protocol` extended to detect `ARCHIPELAGO_NEED_CLARIFICATION` and `ARCHIPELAGO_NEED_PERMISSION` markers and emit `interrupt` messages. `initial_prompt` made optional in `run_headless_adapter`. 20 new tests in `tests/archipelago/test_headless_adapter.py`.

## In Progress

_(none — session start)_

## Backlog

### P0 — Blocks all functionality

1. **Fix repo provisioning**
   `container.py:start()` clones from `/repo` inside the container — which doesn't exist. The `|| true` silently swallows the error, leaving `/workspace` empty. Claude Code works with no code.
   - Decide: mount repo at `/repo` via volume, or clone from a remote URL passed as env var
   - Remove the `|| true` so failures are visible

4. **Remove PTY trust confirmation thread from handler**
   `handler.py:_confirm_trust_and_prompt()` sends `"\n"` as an `InputMessage` over WS. With the headless adapter, this becomes a blank first prompt sent to Claude Code. Then the real feature spec is sent as a second `input` message. Must be replaced with clean prompt delivery.
   - Remove the trust thread entirely (headless mode has no trust prompt)
   - Send the feature spec prompt as the first (and only) input message after the adapter connects

5. **Handle `status: completed` in the handler loop**
   `handler.py` message loop only exits on `status: "exited"`. It ignores `status: "completed"` (task done, awaiting gate). The two-stage protocol (completed → gate check → terminate or resume) is collapsed. Handler must handle `completed` explicitly.

### P1 — Correctness and safety

6. **Add `--dangerously-skip-permissions`**
   In a properly isolated container, this flag eliminates all permission prompts. Currently Claude Code may prompt for tools not in the static `settings.json` allow list.
   - Wire into `_build_claude_cmd()` in headless adapter
   - Confirm `--dangerously-skip-permissions` behavior in `-p` mode (no two-step confirmation issue that exists in interactive mode)

7. **Add `max_turns` to `WorkerConstraints` and wire to Claude CLI**
   No `--max-turns` is passed. A runaway session is only stopped by `timeout_seconds` (blunt). Add `max_turns: int | None` to `WorkerConstraints`, pass as `--max-turns` in `_build_claude_cmd()`.

8. **Raise default `mem_limit_mb` to 2048**
   Current default is 512MB. Claude Code (Node.js) + Python adapter + git + test runners easily exceed this on real workloads, causing silent OOM kills.

9. **Clean up `stty -icrnl` from entrypoint**
   PTY-only dead code. In headless mode there's no PTY. Remove from `entrypoint.sh`.

### P2 — Improvements

14. **Handle SIGTERM in the headless adapter**
    The adapter runs as PID 1 in the container. Docker `stop` sends SIGTERM to PID 1. Python's default SIGTERM behavior is immediate termination — no final status message is sent to the orchestrator, the Claude subprocess may be orphaned, and the orchestrator can't distinguish clean termination from a crash. Need a SIGTERM handler that kills the Claude subprocess cleanly and sends a final `status: exited` before shutting down.

15. **Investigate progress.jsonl approach**
    `progress.jsonl` is intended to give the orchestrator structured output (patches, evidence) and enable crash recovery. Currently Claude Code has no instructions to write it, the handler never delivers those instructions, and the parsing is untested end-to-end. Evaluate whether to keep, simplify, or replace this mechanism before investing in it further.

10. **Wire `--model` from `WorkerConstraints`**
    No model selection — always uses Claude Code's default (Opus 4.6). Add `model: str | None` to `WorkerConstraints`, pass as `--model` to Claude CLI for cost control.

11. **Extract cost/token usage from `result` events**
    Headless adapter's `_map_event_to_protocol()` captures `stop_reason` but not `usage`/`cost` from `result` events. `WorkerConstraints.max_cost_usd` exists but is never enforced. Wire cost data through to `WorkerResult`.

12. **Translate `network_policy` into Docker networking constraints**
    `WorkerConstraints.network_policy` is a string field that's never translated into actual Docker `--network` options in `create_container()`. Network isolation is currently non-functional.

13. **Two-layer CLAUDE.md strategy**
    Bake platform defaults into `/home/claude/.claude/CLAUDE.md` (worker role, protocol). Let project-specific CLAUDE.md come from the cloned repo's `.claude/CLAUDE.md`. Currently no mechanism for this layering.
