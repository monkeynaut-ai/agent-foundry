# Getting Started

This guide builds and validates a small typed process. It uses only in-process
Python functions so you can evaluate Agent Foundry's core declaration and
validation model without Docker, Claude Code, model API keys, or observability
backends.

Agent Foundry is alpha. APIs are being stabilized, but public import paths are
documented in the [public API policy](../reference/public-api.md).

## Install

```bash
pip install agent-foundry
```

Requires Python 3.14.

For local development from this repository:

```bash
pdm install
pdm run test-unit
```

## What You Will Build

The process has two typed steps:

1. Build an outline from an input topic.
2. Build a title from the outline.

Each step declares the Pydantic model it reads and the model it returns. Agent
Foundry validates those boundaries before runtime and preserves the declared
output shape.

## 1. Declare State Models

Process state crosses construct boundaries through Pydantic models.

```python
from pydantic import BaseModel


class DraftInput(BaseModel):
    topic: str


class DraftState(BaseModel):
    topic: str
    outline: str


class DraftOutput(BaseModel):
    topic: str
    outline: str
    title: str
```

## 2. Define Work As Functions

Start with ordinary Python functions. Each function accepts one Pydantic model
and returns another.

```python
def outline(state: DraftInput) -> DraftState:
    return DraftState(topic=state.topic, outline=f"Notes about {state.topic}")


def title(state: DraftState) -> DraftOutput:
    return DraftOutput(
        topic=state.topic,
        outline=state.outline,
        title=f"Understanding {state.topic}",
    )
```

## 3. Wrap Functions In Typed Constructs

`FunctionAction[I, O]` adapts a synchronous Python function into an Agent
Foundry construct.

```python
from agent_foundry import FunctionAction


outline_action = FunctionAction[DraftInput, DraftState](function=outline)
title_action = FunctionAction[DraftState, DraftOutput](function=title)
```

The type parameters matter. They tell Agent Foundry what each action expects
and what it produces.

## 4. Compose A Process

Constructs compose into a process tree. This example uses `Sequence` to run the
two actions in order.

```python
from agent_foundry import Process, Sequence


process = Process(
    root=Sequence[DraftInput, DraftOutput](
        steps=[
            outline_action,
            title_action,
        ]
    )
)
```

## 5. Validate The Process

Validation checks that construct boundaries line up. If a step requires a field
that no earlier step produces, validation fails before runtime.

```python
process.validate()
```

Validation is the first useful feedback loop: you can change process topology,
models, and actions while Agent Foundry keeps checking the typed frame.

## Complete Example

```python
from pydantic import BaseModel

from agent_foundry import (
    FunctionAction,
    Process,
    Sequence,
)


class DraftInput(BaseModel):
    topic: str


class DraftState(BaseModel):
    topic: str
    outline: str


class DraftOutput(BaseModel):
    topic: str
    outline: str
    title: str


def outline(state: DraftInput) -> DraftState:
    return DraftState(topic=state.topic, outline=f"Notes about {state.topic}")


def title(state: DraftState) -> DraftOutput:
    return DraftOutput(
        topic=state.topic,
        outline=state.outline,
        title=f"Understanding {state.topic}",
    )


process = Process(
    root=Sequence[DraftInput, DraftOutput](
        steps=[
            FunctionAction[DraftInput, DraftState](function=outline),
            FunctionAction[DraftState, DraftOutput](function=title),
        ]
    )
)


process.validate()
```

## Where Adapters Fit

The example above uses only the core declaration and validation layers. Agent
Foundry also has runtime and participant integrations for model calls, agent
executors, responder providers, containers, telemetry, and evals.

Those integrations should sit behind explicit seams:

- Use `AICall` when a typed step should call a model provider.
- Use `AgentAction` when a typed step should delegate to an agent executor or
  harness.
- Use custom executors or providers when an application needs a different
  backend.
- Use telemetry and eval adapters to compare behavior without changing process
  declarations.

See [Framework layers and integration boundaries](../architecture/framework-layers-and-boundaries.md)
for the layer map.

Use `run_process` when you are ready to execute a process through the current
runtime. It returns a `RunOutcome` and records run evidence such as lifecycle
events, summaries, and artifacts. The current runtime also carries fields used
by containerized agent execution, so execution examples are covered in the
integration-focused guides rather than this core declaration walkthrough.

## Construct Types

| Construct | Purpose |
|-----------|---------|
| `FunctionAction[I, O]` | Call synchronous Python code. |
| `AsyncFunctionAction[I, O]` | Call async Python code. |
| `GateAction[I, O]` | Pause for external or human input through a responder. |
| `AICall[I, O]` | Call a model provider through a typed model-call contract. |
| `AgentAction[I, O]` | Delegate work to an agent executor or harness. |
| `Sequence[I, O]` | Run child constructs in order. |
| `Loop[I, O]` | Iterate over a collection. |
| `Retry[I, O]` | Repeat a body until a condition passes or attempts are exhausted. |
| `Conditional[I, O]` | Choose a branch based on state. |

## Rules To Remember

- Every construct must be parameterized: `FunctionAction[InputType, OutputType](...)`.
- Inputs and outputs are Pydantic `BaseModel` types.
- Construct boundaries are validated before and during execution.
- Composite constructs can accumulate internal fields, then expose only their
  declared output fields.
- Runtime-specific details belong behind action executors, providers,
  responders, and other adapter seams.

## Next Steps

- Use [Extending Agent Foundry](extending.md) to add custom constructs,
  compilers, validators, executors, and providers.
- Use [Agent containers](agent-containers.md) when you are ready to run an agent
  inside the current containerized Claude Code execution path.
