# Extending Agent Foundry

Agent Foundry is a **platform, not a library**: products add their own construct
types, compilation rules, and execution strategies on top of it rather than
editing its core. There are three extension seams, each open through a registry
or a callable field:

1. **Custom constructs** — define a new `Construct` subclass and register a
   compiler and validator for it.
2. **Custom executors** — swap the behaviour of an action construct (how an
   `AgentAction` or `AICall` actually runs) by passing a callable, with no new
   type.
3. **Registries** — `register_compiler` and `register_validator` dispatch by
   construct type and are duplicate-guarded, so extensions add behaviour without
   touching platform code.

This guide walks through all three with a small, runnable example.

## 1. Define a custom construct

A construct is a Pydantic model parameterized by an input type `I` and an output
type `O`, both `BaseModel` subclasses. It declares the state it reads (`I`) and
writes back (`O`), and lists its children via `child_specs` (leaves return `[]`).

Here is a leaf construct that emits a fixed value, ignoring its input — useful
for seeding state or as a stub. The `value` field is declarative configuration
the compiler will read:

```python
from pydantic import BaseModel

from agent_foundry.constructs.models import Construct


class ConstantAction[I: BaseModel, O: BaseModel](Construct[I, O]):
    """Emit a fixed output value, ignoring the input state."""

    value: O

    def child_specs(self) -> list[tuple[Construct, str]]:
        return []  # a leaf has no children
```

Constructs must be parameterized at use (`ConstantAction[In, Out](...)`); the
base class enforces this. Reading a construct declaration is meant to tell you
exactly what it does, so keep behaviour-defining choices on the construct.

## 2. Register a compiler

A compiler turns a construct into graph nodes. It receives the LangGraph
`StateGraph` being built, the construct instance, and a `CompileContext` whose
`prefix` is the node's scope name. It adds nodes/edges and returns a
`CompileResult(entry_id, exit_id)`.

A leaf adds a single node and returns its id as both entry and exit. The node is
a function from the accumulated state dict to the fields it writes back; return
`model.model_dump()` to merge a typed output into the scope:

```python
from typing import Any

from langgraph.graph import StateGraph

from agent_foundry.compiler import register_compiler
from agent_foundry.compiler.compiler import CompileContext, CompileResult


def _compile_constant_action(
    graph: StateGraph, action: ConstantAction, ctx: CompileContext
) -> CompileResult:
    node_id = ctx.prefix

    def node_fn(state: dict[str, Any]) -> dict[str, Any]:
        return action.value.model_dump()

    graph.add_node(node_id, node_fn)  # type: ignore[arg-type]
    return CompileResult(node_id, node_id)


register_compiler(ConstantAction, _compile_constant_action)
```

Notes:

- **Reading scoped input.** A construct that *uses* its input projects the state
  dict onto `I` and validates it. The platform's built-in leaves do this with an
  internal helper; for your own nodes, take the fields you declared in `I` from
  `state` and validate them with `I.model_validate(...)`.
- **Parameterized generics dispatch by base type.** `ConstantAction[A, B]` is a
  distinct class from `ConstantAction`, so the compiler walks the MRO to find the
  registered base. Register against the base (`ConstantAction`), not a
  parameterization.

## 3. Register a validator

Validators run before compilation and enforce type compatibility, raising a
clear error instead of letting a mismatch fail deep in the graph. Register one
per construct type; the dispatcher also recurses into children for you.

`ConstantAction` should check that the configured `value` actually matches the
declared output type `O`:

```python
from agent_foundry.constructs import register_validator
from agent_foundry.constructs.models import get_type_args


def _validate_constant_action(action: ConstantAction) -> None:
    _input_type, output_type = get_type_args(action)
    if not isinstance(action.value, output_type):
        raise TypeError(
            f"ConstantAction.value is {type(action.value).__name__}, "
            f"but the construct's output type is {output_type.__name__}"
        )


register_validator(ConstantAction, _validate_constant_action)
```

Both registries raise `ValueError` if a type is already registered — this guards
against an extension accidentally overriding a core compiler/validator or an
import-order bug registering twice. Register at import time (module top level),
and make sure the module is imported before you build a process that uses the
construct.

## 4. Use it in a process

Once compiler and validator are registered, the custom construct composes with
the built-ins exactly like a native one:

```python
import asyncio
from pathlib import Path

from agent_foundry.constructs import Process
from agent_foundry.orchestration import run_process, RunCompleted
from agent_foundry.responders.protocol import static_provider


class Empty(BaseModel):
    pass


class Greeting(BaseModel):
    message: str


process = Process(
    root=ConstantAction[Empty, Greeting](value=Greeting(message="hello")),
)

# run_process always requires a workspace volume, base image tag, and a
# responder provider (see the Getting Started guide). A process with no
# AgentAction never creates a container or calls the responder, so any
# placeholder values work here.
outcome = asyncio.run(
    run_process(
        process,
        initial_state=Empty(),
        artifacts_dir=Path("/tmp/af-run"),
        workspace_volume="example-vol",
        base_image_tag="unused:latest",
        responder_provider=static_provider(...),  # a Responder; unused here
    )
)
assert isinstance(outcome, RunCompleted)
assert outcome.output.message == "hello"
```

## 5. Custom executors

The other extension seam needs no new type: action constructs take a callable
that *performs* the work, so you can change how an agent or model call runs by
swapping that field. `AgentAction` and `AICall` both expose an `executor`.

- `AgentAction.executor` contract: `executor(*, construct: AgentAction, prompt: str) -> O`.
  The compiler calls it with keyword arguments and passes the same construct
  instance, so the executor can read everything declared on it (instructions,
  container config, MCP servers, …). The platform ships a containerized executor;
  a product can supply an SDK- or API-backed one, or a fake for tests.
- `AICall.executor` contract: `async (*, construct: AICall[I, O], model_input: I) -> O`.
  When omitted, the default LLM provider path runs. Pass your own to mock
  inference, wrap it with metrics, swap providers, or synthesize a fallback on
  error.

```python
from agent_foundry.constructs import AgentAction


async def fake_executor(*, construct: AgentAction, prompt: str):
    # Return a canned, validated output instead of running a container.
    return construct  # ... build and return an instance of the agent's output type


agent = AgentAction[MyIn, MyOut](
    name="researcher",
    prompt_builder=lambda s: f"Research {s.topic}",
    instructions_provider=lambda s: "You are a research probe.",
    executor=fake_executor,  # swap execution strategy in one line
    # ...
)
```

Because the executor is a field, switching strategies — container vs. SDK vs.
API vs. a test double — is a one-line change in the product declaration; no
platform code changes.

## 6. Custom inference providers

`AICall` makes a single structured LLM call through an **inference provider**.
The platform ships `AnthropicProvider`; a product adds another backend by
implementing `InferenceProvider` and registering a `ModelEntry` for it. (This is
the direct-API path only — it is unrelated to how containerized `AgentAction`s
run, which is governed by the `executor`/base-image seam above.)

A provider maps an `InferenceRequest` to its backend and returns an
`InferenceResult` (the parsed output plus optional token usage):

```python
from agent_foundry.ai_models import (
    InferenceProvider, InferenceRequest, InferenceResult,
    ModelEntry, ModelCapabilities, register_model,
)


class MyProvider(InferenceProvider):
    async def __call__(self, request: InferenceRequest) -> InferenceResult:
        # request carries: model_id, instructions, prompt, parameters, output_type
        output = await my_backend_call(request)          # -> request.output_type
        return InferenceResult(output=output, usage=None)  # usage optional

    async def close(self) -> None:
        ...  # release the backend client


register_model(
    "my-model",
    ModelEntry(
        model_id="my-model-v1",
        provider=MyProvider(),
        capabilities=ModelCapabilities(
            context_window=128_000, max_output_tokens=8_000,
            supports_thinking=False, supports_vision=False,
        ),
    ),
)
```

An `AICall` then references the entry via its `model` field
(`get_model("my-model")`, a built-in `Model.CLAUDE_SONNET_4_6`, or a `ModelEntry`
you construct). `register_model` is duplicate-guarded like the other registries.

**Resilience.** `invoke_ai_call` retries transient errors and fails over down a
chain. For retry to work, a custom provider should override
`is_transient(exc)` to classify its SDK's errors (rate limits / timeouts / 5xx →
`True`); the base default is `False` (no retry). Set `ModelEntry.fallback` to a
default failover target, and a product can override per call with
`AICall.retry` (a `RetryPolicy`) and `AICall.fallbacks` (a `list[ModelEntry]`;
`[]` disables failover).

## Summary

| You want to… | Use | Register / pass |
| --- | --- | --- |
| Add a new construct shape | `Construct` subclass | `register_compiler`, `register_validator` |
| Change how an action runs | existing action construct | `executor=` callable |
| Add an LLM backend for `AICall` | `InferenceProvider` subclass | `register_model` |

All seams keep the construct declaration authoritative and leave the platform
core untouched.
