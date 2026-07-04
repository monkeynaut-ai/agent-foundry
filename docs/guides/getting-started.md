# Getting Started

This guide builds a small typed process, validates its construct boundaries, and
runs it through Agent Foundry's current runtime.

Agent Foundry is alpha. The runtime entry point still takes some orchestration
arguments that matter mainly for agent/container workflows; a function-only
process can pass simple placeholder values for those fields.

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

## 1. Define State Models

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

## 2. Define Actions

Actions are ordinary callables wrapped in typed constructs.

```python
from agent_foundry import FunctionAction


def outline(state: DraftInput) -> DraftState:
    return DraftState(topic=state.topic, outline=f"Notes about {state.topic}")


def title(state: DraftState) -> DraftOutput:
    return DraftOutput(
        topic=state.topic,
        outline=state.outline,
        title=f"Understanding {state.topic}",
    )


outline_action = FunctionAction[DraftInput, DraftState](function=outline)
title_action = FunctionAction[DraftState, DraftOutput](function=title)
```

## 3. Compose A Process

Constructs compose into a process tree. Here a `Sequence` runs the two actions
in order.

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

## 4. Validate Boundaries

Validation checks that the state required by each construct is available and
that the process can produce its declared output.

```python
process.validate()
```

If a step reads a field that no earlier step produces, validation fails before
the process runs.

## 5. Run The Process

`run_process` is async and returns a `RunOutcome`. For this function-only
example, the workspace volume and image tag are recorded in run metadata but no
agent container is started.

```python
import asyncio
import tempfile
from pathlib import Path

from agent_foundry import RunCompleted, StdinResponder, run_process, static_provider


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        outcome = await run_process(
            process,
            initial_state=DraftInput(topic="typed agent workflows"),
            artifacts_dir=Path(tmp),
            workspace_volume="getting-started-workspace",
            base_image_tag="agent-foundry-base:latest",
            responder_provider=static_provider(StdinResponder()),
        )

    if isinstance(outcome, RunCompleted):
        print(outcome.output)
    else:
        raise RuntimeError(outcome)


asyncio.run(main())
```

The completed output is a `DraftOutput` instance:

```text
topic='typed agent workflows' outline='Notes about typed agent workflows' title='Understanding typed agent workflows'
```

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
- Runtime-specific details belong behind action executors, providers, responders,
  and other adapter seams.

## Next Steps

- Use [Extending Agent Foundry](extending.md) to add custom constructs,
  compilers, validators, executors, and providers.
- Use [Agent containers](agent-containers.md) when you are ready to run an agent
  inside the current containerized Claude Code execution path.
