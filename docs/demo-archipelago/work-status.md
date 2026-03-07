# Demo-Archipelago Work Status

## Completed

1. **Create worker CLAUDE.md** — `docker/CLAUDE.md` baked into image at `/home/claude/.claude/CLAUDE.md`. Covers role, task completion marker, interrupt markers, working style. Skipped progress.jsonl instructions (see backlog item 15 to investigate).
2. **Replace stale adapter in image** — Dockerfile now copies `src/archipelago/docker_worker/headless_adapter.py` (build context must be project root: `docker build -f docker/Dockerfile .`). Entrypoint updated: removed `stty -icrnl` (PTY-only dead code), adapter invoked without initial prompt. `_map_event_to_protocol` extended to detect `ARCHIPELAGO_NEED_CLARIFICATION` and `ARCHIPELAGO_NEED_PERMISSION` markers and emit `interrupt` messages. `initial_prompt` made optional in `run_headless_adapter`. 20 new tests in `tests/archipelago/test_headless_adapter.py`.
3. **Remove PTY trust confirmation thread from handler** — Deleted `_confirm_trust_and_prompt()` and all `TRUST_*` constants. Handler now sends feature spec as the first and only input message immediately after adapter connects. Also added pre-commit hooks (ruff format + lint) and a PostToolUse Claude hook for in-session auto-formatting.
4. **Fix repo provisioning** — Clone moved from `container.py` exec_run to `entrypoint.sh`, driven by `REPO_URL`/`REPO_REF`/`GITHUB_TOKEN` env vars. `.netrc` written at startup for credential persistence. `HOME` removed from env allowlist (host HOME broke `.netrc` lookup); `ENV HOME=/home/claude` added to Dockerfile. Shared workspace volume skips clone if `.git` already present.

## In Progress

_(none)_



## Backlog

### P0 — Blocks all functionality

1. **Handle `status: completed` in the handler loop**
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

### P1 — Architecture

9. **Design the test-designer node**
   Archipelago workers will write tests autonomously. Test quality is the single biggest determinant of software quality in TDD. A dedicated test-designer node in the Archipelago graph — invoked by the dev node before writing any tests — can conduct the probing dialogue needed to arrive at the right test design (correct abstraction level, meaningful failure coverage, valid mocks). The node runs its own Claude instance; only the decision document flows back to the dev node, keeping the worker's context clean. Design the node's handler, its input/output contract, and how the dev node signals it needs test design review.

   **Conversation model:** The integration must support a back-and-forth dialogue — the dev node proposes a test design, the test-designer replies with questions or concerns, the dev node revises and resubmits, and so on until the test-designer is satisfied. During this exchange, both the dev container and the test-designer container must retain their Claude sessions (keep context alive via `--resume`) so neither loses the thread of the conversation. When the test-designer is satisfied, it signals approval and its container is terminated.

   **Runaway guard:** Define a maximum number of back-and-forth rounds. If the threshold is reached without the test-designer approving the design, escalate to a human-in-the-loop breakpoint — surface the full exchange and ask for a decision before proceeding.

10. **Investigate: probing/clarifying question node for the dev node**
    The dev node needs a way to ask probing and clarifying questions and receive answers during autonomous operation. Investigate a general-purpose "consult" node that the dev node can call when it needs input — for test design, architecture decisions, ambiguous requirements, etc. This may overlap with or subsume the test-designer node. Determine whether these are the same node (a general consultant) or distinct (test-designer as a specialist).

### P1 — Architecture

17. **Design concurrent repo access between nodes in the same graph instance**
    Nodes in the same graph instance share a Docker named volume mounted at `/workspace`. If two nodes run concurrently (e.g., dev_test writing changes while a reviewer reads), there is no file locking — Docker volumes allow concurrent access but provide no coordination. Investigate whether LangGraph's execution model prevents true simultaneity on the same thread, or whether explicit coordination is needed (e.g., a write lock, a hand-off protocol, or a graph topology constraint that serializes access to the shared volume). Define the policy before any multi-node workflow is wired up.

### P2 — Agent Foundry Core

16. **Implement error and exception handling in Agent Foundry**
    Review and harden error and exception handling across the Agent Foundry core (capability registry, compiler, wiring, retriever, execution). Identify unhandled or poorly handled failure paths, define consistent error types, and ensure failures surface with actionable messages rather than raw exceptions or silent swallows.

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
