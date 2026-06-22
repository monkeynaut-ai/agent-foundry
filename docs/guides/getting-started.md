# Building on Agent Foundry

## Install

Agent Foundry is a local dependency. In your package's `pyproject.toml`:

```toml
dependencies = [
    "agent-foundry @ file:///${PROJECT_ROOT}/../agent-foundry",
]
```

## Core concepts

**1. Define state models** — Pydantic BaseModels for input/output at each step:

```python
from pydantic import BaseModel

class MyInput(BaseModel):
    data: str

class MyOutput(BaseModel):
    data: str
    result: str
```

**2. Build primitives** — compose a tree from leaf actions and control flow:

```python
from agent_foundry.primitives import (
    FunctionAction, Sequence, Loop, Retry, Conditional, PrimitivePlan
)

action = FunctionAction[MyInput, MyOutput](
    function=lambda s: MyOutput(data=s.data, result=s.data.upper())
)
plan = PrimitivePlan(root=action)
```

**3. Run it** — `run_primitive_plan` is the single public entry point. It is `async`,
takes keyword-only arguments, and returns a `RunOutcome` (`RunCompleted` /
`RunAborted` / `RunFailed`) whose `.output` holds the typed final state:

```python
from agent_foundry.orchestration.runner import run_primitive_plan
from agent_foundry.orchestration import RunCompleted

outcome = await run_primitive_plan(
    plan,
    initial_state=MyInput(data="hello"),
    artifacts_dir=run_dir,            # Path where this run writes lifecycle/summary
    workspace_volume="my-vol",        # Docker volume backing agent workspaces
    base_image_tag="agent-foundry-base:latest",
    responder_provider=my_provider,   # supplies responses to GateAction interactions
)

if isinstance(outcome, RunCompleted):
    print(outcome.output)  # MyOutput(data='hello', result='HELLO')
```

For a complete, runnable end-to-end example (including telemetry wiring), see the
[README](../../README.md) and `examples/mlflow_demo/`.

## Primitive types

| Primitive | Purpose | Key fields |
|-----------|---------|-----------|
| `FunctionAction[I, O]` | Call a function | `function: Callable[[I], O]` |
| `GateAction[I, O]` | Block for human input | `interaction: str`, `prompt_key: str` |
| `Sequence[I, O]` | Run steps in order | `steps: list[Primitive]` |
| `Loop[I, O]` | Iterate over collection | `over: Callable[[I], list]`, `item_key: str`, `body: Primitive` |
| `Retry[I, O]` | Repeat until condition | `max_attempts: int`, `until: Callable[[I], bool]`, `body: Primitive` |
| `Conditional[I, O]` | Branch on state | `condition: Callable[[I], bool]`, `then_branch`, `else_branch` |

## Rules

- Every primitive is parameterized: `FunctionAction[InputType, OutputType](...)`
- Types must match at boundaries (exact match, not subtype)
- Composite primitives (Sequence, Loop, etc.) isolate state — only I/O fields cross boundaries
- Retry exits normally on exhaustion — check domain state in a parent Conditional to handle it
- Conditional without else_branch is a "detour" — all four types must be identical

## Extending with custom primitives

Register a compiler for your own primitive type:

```python
from agent_foundry.primitives import Primitive
from agent_foundry.compiler import register_compiler

class MyCustomPrimitive[I, O](Primitive[I, O]):
    custom_field: str

def _compile_my_custom(graph, prim, prefix, gate_ids):
    # Add nodes/edges to graph
    # Return (entry_node_id, exit_node_id)
    ...

register_compiler(MyCustomPrimitive, _compile_my_custom)
```

## What to test

- State models construct and validate correctly
- Primitive trees pass validation (`plan.validate()`)
- `run_primitive_plan(plan, input)` produces expected typed output
- State isolation — internal fields don't leak across boundaries
