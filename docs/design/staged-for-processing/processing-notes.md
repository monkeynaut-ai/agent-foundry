# What to Do

Assessment of system-resilience-and-resume.md:1:

## Implemented

- Run artifacts exist: lifecycle.jsonl, summary.txt, inspect-workspace.sh, per-agent logs, per-turn stream.jsonl, envelope.json, output.json.

- Failed containers can be retained via pause_on_failure.
- Forensic capture exists: docker-inspect.json, cgroup-memory.txt, exit code, OOM, memory peak, API error fields.

- Claude session IDs are captured from stream-json and stored on the live container.

- REUSE_RESUME can resume the same Claude session within the same live
container/run path.

- Turn API retries now exist and emit TURN_API_RETRIED.

## Not Implemented

- No agent-foundry resume <run-id> or generic resume API.
- No run-state reader that uses lifecycle.jsonl to skip completed stages.
- No cross-run workspace remount/resume semantics.
- No durable checkpoint model for typed process state.
- No RUN_RESUMED / AGENT_INVOCATION_RESUMED events.
- No workspace snapshots before stages.
- No stuck-shell scanner/watchdog.

## Contradictions / Drift

- The doc says session IDs are “stored on the lifecycle record”; current code stores them on LiveContainer and in raw stream.jsonl, not as first-class lifecycle fields.

- The doc is Archipelago-specific: archipelago resume, named pipeline agents,
    workspace volume naming, role markdown, etc.

- “All-or-nothing” is still directionally true for resume, but current
    run_process returns structured RunOutcome and preserves more failure evidence
    than the doc implies.

- The “orchestration one-shot retry” part is now more concrete: turn API retry
    exists with lifecycle evidence.

## OSS/framework Fit

- Strong fit as a problem statement: stable evidence, resumability,
    checkpointing, and failure recovery matter for experimentation.

- Weak fit as written: too product/platform-specific. For OSS Agent Foundry,
    this should become a framework-level “resilience and resume contract” design,
    not an Archipelago resume-command design.

I would keep it archived, but mine it for a future issue/design around a generic checkpoint/resume contract.
