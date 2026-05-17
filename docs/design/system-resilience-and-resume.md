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
