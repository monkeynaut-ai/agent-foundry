# Checkpoint And Resume Contract

Agent Foundry should provide a framework-level checkpoint and resume contract so
applications can recover expensive agentic runs without binding the core to one
product CLI, workspace layout, or agent harness.

This design mines the useful parts of the archived system-resilience note and
reframes them for the OSS/framework pivot.

## Problem

Agentic systems are expensive to rerun from scratch. A late failure can waste:

- completed typed outputs
- model calls and tool calls
- agent session context
- workspace mutations
- debugging evidence already written to artifacts

Agent Foundry already records substantial evidence, but the runtime does not yet
consume that evidence to continue a failed run. The missing piece is a generic
contract for checkpoint creation, checkpoint discovery, and resume planning.

## Goals

- Preserve a stable, typed boundary for completed construct outputs.
- Let applications resume from durable checkpoints without re-running completed
  work by default.
- Keep resume mechanics independent of a specific product CLI.
- Support adapter-specific continuation where available, such as Claude Code
  session resume.
- Make resumed runs explicit in lifecycle evidence.
- Let applications decide how much to trust prior outputs and workspace state.

## Non-Goals

- Do not introduce an Archipelago-specific `resume` command in Agent Foundry
  core.
- Do not require every agent harness to support mid-agent continuation.
- Do not guarantee side-effect rollback without an application-provided workspace
  snapshot mechanism.
- Do not make all constructs implicitly idempotent.

## Current Building Blocks

Agent Foundry already has pieces a resume system can build on:

- `run_process(...)` writes a stable run directory.
- `lifecycle.jsonl` records run, construct, agent invocation, turn, retry, and
  failure events.
- `RunOutcome` distinguishes completed, aborted, and failed runs.
- `RunContext.artifacts_dir` gives executors a durable artifact root.
- `AgentAction` writes per-turn `stream.jsonl`, `envelope.json`, and
  `output.json`.
- Container failures capture forensic evidence such as `docker-inspect.json`,
  `cgroup-memory.txt`, exit code, OOM state, memory peak, and API error fields.
- `ContainerReusePolicy.REUSE_RESUME` can pass a captured Claude session id back
  into the same live container path.

These are evidence and continuation building blocks, not a complete resume
contract.

## Proposed Concepts

### Checkpoint

A checkpoint is a durable record that says a construct boundary completed and
produced a typed output.

Minimum fields:

- `run_id`
- `checkpoint_id`
- `node_id`
- `construct_type`
- `construct_name`
- `input_type`
- `output_type`
- `output`
- `created_at`
- `artifact_refs`
- `state_hash` or equivalent integrity metadata

The checkpoint output must validate against the declared output model before it
is reused.

### Resume Manifest

A resume manifest summarizes what can be trusted from a previous run.

It should include:

- source run id
- checkpoint list
- terminal run outcome
- failed node, if known
- artifact root
- workspace reference, if any
- adapter continuation references, if any
- validation status for each checkpoint

The manifest can be derived from lifecycle/artifact evidence, generated as a
separate file during the original run, or both.

### Resume Plan

A resume plan is the application/runtime decision about how to continue.

Examples:

- skip completed checkpoints and restart at the first failed downstream node
- revalidate selected checkpoints before skipping them
- discard checkpoints after a specific node
- resume a harness session for the failed agent when the adapter supports it
- start a fresh harness session while reusing prior typed outputs

The plan should be explicit so resume behavior is inspectable and testable.

### Adapter Continuation

Some adapters can resume more than typed state:

- a container adapter may reuse a workspace volume
- a Claude Code adapter may resume a session id
- a workflow engine adapter may resume from its own durable execution cursor
- a service-backed agent adapter may expose provider-specific continuation ids

Agent Foundry core should model these as optional adapter-provided continuation
references. The core contract should not assume that every adapter can continue
mid-agent.

## Lifecycle Events

Resume should be visible in the lifecycle stream.

Candidate events:

- `run_resumed`
- `checkpoint_created`
- `checkpoint_reused`
- `checkpoint_rejected`
- `resume_plan_created`
- `agent_invocation_resumed`

These should be treated as wire-stable lifecycle event names once introduced.

## Trust Model

Resume is a trust decision. The default should be conservative and explicit.

Agent Foundry should support at least these modes:

- **trust validated checkpoints**: reuse outputs that validate against the
  declared output type and integrity metadata
- **revalidate checkpoints**: run application-provided validators before reuse
- **replay from selected node**: ignore checkpoints at or after a chosen boundary
- **fresh run**: keep prior evidence but do not reuse it

Applications own semantic validity. Agent Foundry can validate type shape,
artifact presence, hashes, and adapter references, but it cannot know whether an
old output remains correct after external state changes.

## Workspace State

Typed checkpoints and workspace state are related but not the same.

For containerized agents, a checkpoint may depend on workspace mutations. The
resume contract should allow a workspace reference but keep snapshot mechanics
pluggable:

- Docker volume name
- filesystem path
- object-store snapshot id
- workflow-engine artifact reference
- application-defined workspace token

Workspace snapshots are valuable, but they should be an adapter/application
capability rather than a prerequisite for all Agent Foundry usage.

## Open Questions

- Should checkpoints be written for every construct type or only selected
  resumable constructs?
- Should checkpoint persistence be always on, opt-in per process, or opt-in per
  construct?
- Where should checkpoint files live relative to existing artifacts?
- How should schema/version drift be handled when resuming after code changes?
- What is the minimal public API for building and applying a resume plan?
- How should resume interact with `Retry`, `GateAction`, and responder pauses?
- Should adapter continuation references be opaque strings or typed models?

## Implementation Shape

A small first version could include:

1. Add a checkpoint artifact schema and writer for completed construct outputs.
2. Emit checkpoint lifecycle events.
3. Add a manifest reader that reconstructs reusable checkpoints from a prior
   run directory.
4. Add a resume-plan model that records which checkpoints will be reused.
5. Add tests proving typed checkpoint validation and rejection behavior.
6. Defer mid-agent continuation until the checkpoint contract is stable.

This sequence gives Agent Foundry a reusable framework primitive before adding
adapter-specific resume behavior.
