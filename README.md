# Agent Foundry

Agent Foundry is a typed, boundary-enforced framework for declaring and running
agentic systems. Builders compose processes from declared constructs, validate
state boundaries, and run them through adapter seams for workflow engines, agent
harnesses, model providers, tools, and observability backends.

Those seams are the long-term portability strategy. The adapter ecosystem is
still a work in progress: Agent Foundry provides the core abstractions and
initial integrations, while broader backend and provider support still needs to
be built and validated.

> **Status: alpha.** Agent Foundry is pre-1.0 and APIs may change.
> License: MIT. See [LICENSE](LICENSE).

## Why Agent Foundry

Agentic systems are still early. Teams are learning which instructions work,
how memory should be managed, what topology fits a use case, which models are
worth their cost, where humans should stay in the loop, and how agent behavior
should be evaluated.

Agent Foundry is for running those experiments without rebuilding the whole
system each time. It keeps the durable shape of an agentic system stable while
the volatile parts change: prompts, models, tools, memory strategies, agent
harnesses, execution backends, and observability systems.

The core idea is simple: process state crosses construct boundaries through
declared Pydantic models. The framework validates those boundaries before and
during execution so dynamic agent behavior has an inspectable process frame.

## Core Concepts

A process is a tree of typed constructs.

**Control-flow constructs** shape the process:

- **Sequence**: run steps in order.
- **Loop**: iterate over a collection.
- **Retry**: repeat until a condition passes or attempts are exhausted.
- **Conditional**: branch on state.

**Action constructs** do work at the leaves:

- **FunctionAction**: call in-process Python code.
- **AsyncFunctionAction**: call async Python code.
- **GateAction**: pause for human or external input.
- **AICall**: call a model provider through a typed model-call contract.
- **AgentAction**: delegate work to an agent executor or harness.

Each construct declares the Pydantic input model it reads and the output model it
returns. Composite constructs accumulate internal state and choose which typed
fields leave their scope.

## Example

```python
from pydantic import BaseModel

from agent_foundry.constructs import FunctionAction, Process, Sequence


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

`process.validate()` checks that the declared state fields line up across the
construct tree. `run_process(...)` executes the process and returns a typed
`RunOutcome`; see [Getting started](docs/guides/getting-started.md) for a full
runnable example.

## Current Integrations

Agent Foundry currently includes:

- A LangGraph-backed compiler/runtime for bounded process execution.
- Pydantic-based input and output contracts.
- Function, async function, human gate, model call, and agent action constructs.
- A containerized Claude Code agent execution path.
- Lifecycle events and run summaries.
- OpenTelemetry span emission.
- An optional MLflow adapter.
- An evaluation harness for model and process experiments.

The goal is to make more of these choices replaceable over time. New adapters
should preserve Agent Foundry's process, state, error, lifecycle, and output
semantics, ideally through shared contract tests.

## Install

```bash
pip install agent-foundry
pip install agent-foundry[mlflow]  # optional MLflow adapter
```

Requires Python 3.14.

## Documentation

| Area | Where |
|------|-------|
| Getting started | [docs/guides/getting-started.md](docs/guides/getting-started.md) |
| Agent containers | [docs/guides/agent-containers.md](docs/guides/agent-containers.md) |
| Extending Agent Foundry | [docs/guides/extending.md](docs/guides/extending.md) |
| Vision | [docs/vision.md](docs/vision.md) |
| Architecture | [docs/architecture/](docs/architecture/) |
| Design docs | [docs/design/](docs/design/) |
| Reference | [docs/reference/](docs/reference/) |
| Contributing | [CONTRIBUTING.md](CONTRIBUTING.md) |

## Out Of Scope

Agent Foundry is not:

- a hosted platform
- a general-purpose workflow engine
- only a model provider abstraction
- a replacement for every agent framework
- a promise of backend portability before adapters exist

## Design Promises

- Process declarations stay framework-neutral where possible.
- Typed I/O boundaries are non-negotiable.
- Provider- and runtime-specific details belong in adapters.
- Escape hatches are allowed, but should be marked non-portable.
- Adapter compatibility should be validated with shared contract tests as
  adapters are added.

## License

MIT. See [LICENSE](LICENSE).
