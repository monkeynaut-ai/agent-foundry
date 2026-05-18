# System resilience and resume

**Date:** 2026-05-17
**Status:** Draft — problem statement and option space

## Problem

A run in agent-foundry today is all-or-nothing. Any failure — agent
exec error, container OOM kill, an agent emitting `FailureOutcome`,
an upstream API blip that exhausts retry, a kill from outside —
terminates the entire run with `RUN_FAILED`. The next attempt starts
from scratch:

- Fresh workspace volume (the prior one survives but is unused).
- Fresh container, including warmup cost.
- Re-run every earlier-completed agent, even though their outputs are
  intact on disk.
- Re-pay every token, every minute, every model invocation.

Concrete recent examples:

- Implementer reached a final `StructuredOutput` envelope, the
  commit landed on the workspace branch, then the orchestration
  hung on a leftover `tail -f`. Killing the container loses every
  agent that ran before it (designer, change_set_planner,
  tdd_planner, tester) — none of their work is reused.
- An upstream API 500 that exhausts claude's internal retries AND
  the orchestration's one-shot retry kills the run mid-stage. The
  prior stages' work survives on disk but isn't reused.
- A bad cert in `secrets/` for the fault-injection proxy causes
  every stage to fail at TLS handshake. After fixing the cert, the
  next run replays every stage from scratch.

Cost grows linearly with how far into the pipeline a run gets
before failing. Late-stage failures (implementer, pr_creator) are
the most expensive ones to replay.

## Building blocks that already exist

- **Workspace volume persists.** `archipelago-ws-<feature>-<ts>` is
  retained at run teardown; nothing prunes it automatically.
- **`lifecycle.jsonl` records what happened.** Every agent
  invocation's start/complete/fail, every turn, every session id —
  all durable.
- **Per-turn session ids.** Captured via the `system/init` event
  and stored on the lifecycle record. `claude --resume <id>` is
  already supported in agent-foundry's executor.
- **Forensic artifacts on disk.** `container.log`, `docker-inspect.json`,
  `cgroup-memory.txt`, per-turn `stream.jsonl`, optional
  `inspect-container.sh` — the postmortem trail is rich.

The orchestration layer doesn't currently consume any of these for
continuation; it just writes them.

## Option space (three tiers, increasing scope)

### Tier 1 — resume at the failed stage

Add an `archipelago resume <run-id>` command that:

- Re-mounts the same workspace volume as the failed run.
- Reads the failed run's `lifecycle.jsonl` to identify which agents
  completed and which one failed.
- Trusts completed agents' outputs as-is (their artifacts and
  workspace mutations are already on disk).
- Restarts the pipeline from the next agent after the last
  successful one.

Pros: smallest blast radius; doesn't require any agent changes; the
common case (one stage broke, the rest were fine) is covered.
Cons: assumes prior-stage outputs are still semantically valid; if
the workspace drifted (e.g., a partial commit on a previous run
left it in an odd state), the resume picks up corrupt state.

Open question: how does archipelago name the resumed run? Does
`runs/<original-id>-resume-1/` make sense, with lifecycle continued
in the new directory? Or a single run-id with multiple "attempt"
sub-stamps?

### Tier 2 — resume mid-agent

When the failed agent itself can be resumed (claude session
captured, not OOM-killed):

- Use the captured session id from the last `agent_invocation_started`
  to re-enter the same agent with `claude --resume <id>`.
- Send a continuation prompt ("upstream interrupted you; resume
  from your current state").
- Carry forward the same workspace mounts and env.

Pros: avoids re-running an expensive agent that was 80% done.
Cons: session state on Anthropic's side may have expired; mid-tool-call
state is ambiguous (a tool ran but its result wasn't acknowledged →
agent may re-invoke, with possible duplicate side effects); requires
the agent's role markdown to handle the "you're being resumed" case
robustly.

Probably gated on: empirical evidence that mid-agent restarts (not
just stage-skip) are a frequent need. Without that data, Tier 1 may
suffice.

### Tier 3 — idempotent agents

Have each agent verify workspace state before acting:

- Implementer: check whether the target task's commit already
  exists before re-implementing.
- Tester: check whether the expected failing test is already present.
- Designer: check whether `design.md` already exists and matches
  the change set.

Pros: makes Tier 1 and Tier 2 safe under more conditions; bare-handed
re-runs of the whole pipeline become harmless.
Cons: invasive (every agent's role markdown changes); discipline
required to keep new agents idempotent; some operations are
genuinely non-idempotent (cleanups, irreversible mutations).

Honest framing: ongoing hygiene, not a single project. Worth
adopting case-by-case as agents are touched, not as a sweep.

## Orthogonal resilience improvements

- **Workspace snapshots before each stage.** A copy-on-write
  snapshot of the workspace volume taken before each agent starts;
  on failure, the resume command can roll back to the snapshot
  before the failed stage rather than trusting that the workspace
  is clean. Useful when failed-stage cleanups are imperfect.
- **Pre-warmed container pool.** Avoid paying container boot cost
  per agent. Less about resilience, more about throughput; mention
  here because the same workspace-+-container-mount machinery
  enables it.
- **Cleanup policy for retained artifacts.** Workspace volumes,
  failed containers, and run directories all accumulate. Pairs
  naturally with the Tier 1 resume command (which needs the
  artifacts to function).
- **Continuation-aware lifecycle events.** Add `RUN_RESUMED` and
  `AGENT_INVOCATION_RESUMED` so the lifecycle stream of a resumed
  run is self-describing.

## Stuck-shell detection inside running agents

The implementer agent has gotten stuck multiple times because claude
spawned a bash with a polling loop (`until grep …; sleep N; done`,
`tail -f`, etc.) whose exit condition never fires. The bash never
returns, so `docker exec` never returns, so the orchestration's turn
loop waits indefinitely. The 2026-05-17 runs cost hours each before
manual kill. Two complementary detection paths:

### Host-side `/proc` scanner

A standalone diagnostic that walks the host's process table looking
for shells matching the danger pattern — `until grep … sleep`,
`tail -f /tmp/.../tasks/<id>.output`, long-etime polling chains.
Reports PID, etime, and the offending cmdline. Catches stuck shells
in BOTH the host's own claude-code session AND in any agent worker
container (worker shells appear in the host PID namespace via
docker's default sharing).

Cheap to write (a ~10-line bash or python script) and run on demand.
Doesn't require any agent-foundry integration. Useful as a
"something feels stuck" command an operator can run while a long
run is in progress.

Limitation: no automatic action. Reports the symptom; the operator
decides whether to kill the offending PID and accept the run's
death, or keep waiting.

### In-orchestrator watchdog

Inside the per-turn loop in
`agent_foundry/orchestration/container_executor.py`, track wall-clock
time since the last event (`stream-json` line) read from the running
`docker exec`. If that exceeds a configurable threshold (e.g. 5–10
minutes of total silence from claude), open a side `docker exec` into
the same container, sample its process tree, and grep for the danger
pattern. On a match:

- Emit a new lifecycle event (`TURN_STUCK_SHELL_DETECTED`) carrying
  the offending PID, etime, and the matched cmdline.
- Persist the snapshot to `<run>/<agent>/turns/<n>/stuck-shell.txt`.
- Optionally (configurable, default off) `docker exec ... kill <pid>`
  the offending bash to unblock the parent `claude` exec. Claude
  then receives the bash's exit and can decide its next action —
  in practice it will surface the error through `StructuredOutput`,
  letting the orchestrator handle it as a turn failure rather than
  an indefinite hang.

This is the right long-term answer for agent-foundry: it makes the
orchestration self-healing instead of relying on operator vigilance.
Pairs naturally with Tier 1 resume — a stuck-and-killed agent
becomes a resumable failure rather than a wedged run.

Open questions:
- Threshold value. Too short → false positives on legitimate
  long-running tests; too long → wasted hours before detection.
  A per-agent override (implementer's commit stage needs more
  patience than designer's reads) may be necessary.
- Pattern catalogue. Start with the two patterns observed
  (`until.*sleep`, `tail -f /tmp/claude-1000/.*/tasks/`); accept
  that this is a living list.
- Whether to act (kill) or just report. Reporting-only is the
  safer default; killing is a foot-gun if the pattern matches a
  legitimate command. Make killing opt-in per run.

## Recommended sequencing

1. Ship Tier 1 first. Lowest risk, biggest single win for the
   late-stage-failure cost problem.
2. Watch the failure data once Tier 1 is in. If "I needed to resume
   mid-agent" becomes a frequent ask, then Tier 2.
3. Tier 3 as ongoing hygiene; pick up case-by-case.
4. Orthogonal items handled as their own tickets when they pinch.

## Open questions

- Naming and on-disk layout for resumed runs (separate run-id vs.
  appended attempt log).
- Whether a resume should re-execute idempotent prior stages "just
  to be safe" or trust them blindly. Probably trust by default with
  an opt-in `--reverify` flag.
- How to express resume-eligibility per agent (some agents may
  declare "I am not safely resumable").
