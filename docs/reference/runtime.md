# Runtime Accessors

`agent_foundry.runtime` exposes run-scoped helpers for code executing inside a
running Agent Foundry process.

Use these helpers from `FunctionAction` and `AsyncFunctionAction` bodies when
the function needs run metadata, artifact paths, lifecycle events, cancellation
state, or the configured responder.

```python
from agent_foundry import runtime
```

The accessors read the active run context managed by Agent Foundry. They do not
require user functions to accept or thread a `RunContext` argument.

Outside a running process, accessors return safe defaults:

- `None` for optional values
- `False` for cancellation state
- no-op behavior for event emission

## Accessors

### `runtime.run_id()`

Returns the current run id, or `None` outside a run.

```python
run_id = runtime.run_id()
```

Use this when writing product logs or correlating external records with an Agent
Foundry run.

### `runtime.artifacts_dir()`

Returns the current run's artifact directory as a `Path`, or `None` outside a
run.

```python
path = runtime.artifacts_dir()
if path is not None:
    (path / "custom-note.txt").write_text("done", encoding="utf-8")
```

Prefer writing under this directory for run-scoped evidence that should travel
with the rest of the run artifacts.

### `runtime.emit(kind, **fields)`

Emits a product-defined lifecycle event.

```python
runtime.emit("retrieval_completed", documents=5)
```

The event is written as a domain lifecycle record. It is a no-op outside a run.

Use domain events for application-specific evidence that should appear beside
Agent Foundry's own lifecycle events.

### `runtime.cancelled()`

Returns `True` when the active run has been cancelled, otherwise `False`.

```python
if runtime.cancelled():
    return Output(status="cancelled")
```

Use this in long-running function actions that can cooperatively stop between
units of work.

### `runtime.responder()`

Returns the active run's configured responder, or `None`.

```python
responder = runtime.responder()
if responder is None:
    return Output(answer="no responder configured")
```

This is mainly useful from `AsyncFunctionAction`, where the function can await
the responder directly. Callers still need to construct the appropriate
responder request and context models from `agent_foundry.responders`.

## Example

```python
from pydantic import BaseModel

from agent_foundry import AsyncFunctionAction, runtime


class Input(BaseModel):
    item_count: int


class Output(BaseModel):
    status: str


async def process_items(state: Input) -> Output:
    runtime.emit("processing_started", item_count=state.item_count)

    if runtime.cancelled():
        runtime.emit("processing_cancelled")
        return Output(status="cancelled")

    artifacts_dir = runtime.artifacts_dir()
    if artifacts_dir is not None:
        (artifacts_dir / "item-count.txt").write_text(
            str(state.item_count),
            encoding="utf-8",
        )

    return Output(status="done")


action = AsyncFunctionAction[Input, Output](function=process_items)
```

## Relationship To `RunContext`

`RunContext` is an orchestration contract object. Most application code should
not accept it directly.

Use `agent_foundry.runtime` when user-defined function bodies need run-scoped
state. Use `RunContext` only when implementing executors, adapters, or run hooks
that are already part of the orchestration layer.
