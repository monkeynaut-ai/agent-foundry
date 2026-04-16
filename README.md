# Agent Foundry

A platform for defining, running, and managing agent systems.

## Authentication

ACP containers require exactly one of these environment variables:

**Option 1: OAuth token (Claude Pro/Max subscription)**
```bash
claude setup-token          # generates a long-lived token
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-..."
```

**Option 2: API key (API billing)**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

The `DEFAULT_ENV_ALLOWLIST` in `acp/container.py` passes these from the host environment into containers. The entrypoint script validates that exactly one auth method is present and rejects the container if both or neither are set.

## Lifecycle events: platform vs. domain

Agent Foundry writes an append-only event stream to `<run_dir>/lifecycle.jsonl` during every run. Events fall into two categories:

**Platform events** — a fixed, enumerated vocabulary owned by Agent Foundry. Emitted by the executor, registry, and compiler nodes. Examples: `run_started`, `agent_container_started`, `agent_invocation_started`, `turn_started`, `turn_completed`, `responder_requested`, `function_action_started`, `run_ended`. The full list is `LifecycleEvent` in `agent_foundry/orchestration/lifecycle_events.py`. Products do not define new platform events and do not emit these types themselves.

**Domain events** — open-schema, product-defined. Products emit their own events via `run_ctx.lifecycle_writer.append_run_event(...)` from within a `FunctionAction`'s function or any other code that has access to the `AgentRunContext`. The convention is:

```python
run_ctx.lifecycle_writer.append_run_event({
    "type": LifecycleEvent.DOMAIN.value,        # wire constant "domain"
    "kind": "<product-chosen-subtype>",          # e.g. "step_committed"
    # ...any additional fields the product wants to record...
})
```

`LifecycleEvent.DOMAIN` (= `"domain"`) is the **escape hatch** that lets a product extend the lifecycle stream with its own vocabulary without needing to modify Agent Foundry's enum. Consumers of the jsonl (e.g., a product-specific summary renderer) filter by `type == "domain"` and route on the `kind` subfield. Downstream examples: Archipelago's planned `summary.txt` renderer that groups a run's activity by change set and step — each boundary is emitted as a `DOMAIN` event with a `kind` like `"change_set_started"` or `"step_completed"`.

Rule of thumb: if the event describes something the platform does (start a container, run a turn, invoke a function), that's a platform event — emitted automatically. If the event describes something the *product* does (commit a change set, escalate to a human, mark a review cycle complete), that's a `DOMAIN` event — the product emits it explicitly.
