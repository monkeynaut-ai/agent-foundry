# Framework Layers and Integration Boundaries

This document maps the major responsibilities inside Agent Foundry. It is not a
symbol-by-symbol API catalog; use the public API policy for import stability.

The boundary that matters most for the OSS framework pivot is the distinction
between the durable framework core and the current integrations that perform
work on its behalf.

## Layer Map

| Layer | Owns | Main packages | Extension seams |
| --- | --- | --- | --- |
| Core declaration | Typed process contracts | `agent_foundry`, `agent_foundry.constructs`, shared `agent_foundry.models` | custom constructs and action fields |
| Validation and compiler | Boundary checks and graph lowering | `agent_foundry.constructs.validators`, `agent_foundry.compiler` | `register_validator`, `register_compiler` |
| Runtime and orchestration | Process execution and run evidence | `agent_foundry.orchestration`, `agent_foundry.runtime`, `agent_foundry.responders` | run hooks, responder providers, executors |
| Participant integrations | External systems that perform work | `agent_foundry.ai_models`, `agent_foundry.agents`, container executor, MCP config | model providers, model registry, agent executors |
| Observability and evals | Evidence, telemetry, and experiment comparison | `agent_foundry.telemetry`, `agent_foundry.mlflow_adapter`, `agent_foundry.evals` | telemetry config, observability adapters, eval runners |

## Core Declaration Layer

The core declaration layer defines typed process contracts. It should describe
what a process is, what each step reads and returns, and what typed state can
cross each boundary.

This layer owns:

- `Process` and typed `Construct[I, O]` trees.
- Control-flow constructs: `Sequence`, `Loop`, `Retry`, and `Conditional`.
- Leaf actions: `FunctionAction`, `AsyncFunctionAction`, `GateAction`,
  `AICall`, and `AgentAction`.
- Pydantic input and output models as boundary contracts.

Declarations should remain as portable as practical. Backend-specific details
are acceptable when they are explicit adapter fields or are clearly marked as
non-portable current integration behavior.

## Validation and Compiler Layer

The validation/compiler layer proves that declarations are internally coherent
and lowers them into the current execution backend.

This layer owns:

- `process.validate()` and construct validation.
- Construct-specific validators.
- Compiler registration and `compile_process`.
- State projection and merge behavior across construct boundaries.
- Loud failures for unknown constructs unless an extension registers support.

LangGraph is the current compiler/runtime backend. That is an implementation
choice, not the whole framework boundary.

## Runtime and Orchestration Layer

The runtime/orchestration layer executes compiled processes and records what
happened during a run.

`agent_foundry.orchestration` owns:

- `run_process`.
- `RunContext`.
- run outcomes such as `RunCompleted`, `RunFailed`, and `RunAborted`.
- lifecycle events, artifacts, run summaries, hooks, and cancellation.
- current container registry ownership for containerized agent execution.

`agent_foundry.runtime` exposes run-scoped accessors for user code executing
inside a process. It is a convenience surface for code that needs the current
run id, artifacts directory, lifecycle emission, cancellation state, or
responder, not the orchestration engine itself.

The runtime layer should preserve declaration-layer semantics and return typed
outcomes instead of leaking backend-specific execution details.

## Participant Integrations

Participants are external systems that perform work for declared actions.

Examples:

- `AICall` uses `agent_foundry.ai_models` providers, model entries, and the
  model registry to call model APIs.
- `AgentAction` delegates work through an executor callable.
- The current container executor runs Claude Code in Docker.
- MCP server declarations configure tool authority for current agent execution.
- `agent_foundry.responders` provides the human/operator participant boundary
  for clarification and permission flows.

The integration rule is:

> Declarations hold typed contracts; adapters own provider, tool, harness, and
> backend protocol details.

The current Docker + Claude Code path is one participant integration. It should
not be mistaken for the whole framework.

## Observability and Evals

Observability and eval systems consume run evidence and support comparison
across experiments. They should not force changes to process declarations.

This layer owns:

- lifecycle events and summaries as run evidence.
- `agent_foundry.telemetry` as vendor-neutral OpenTelemetry configuration and
  span emission.
- `agent_foundry.mlflow_adapter` as an optional observability backend adapter.
- adapter-specific translation of attributes, parameters, metrics, and
  artifacts.
- `agent_foundry.evals` typed suite/report models and runner adapters.

Evals can target individual `AICall` behavior, full process execution, or
agent-oriented workflows. Runner-specific dependencies should stay behind eval
runner boundaries when possible.

## Dependency Direction

Agent Foundry should keep dependency direction clear:

- Declarations should not depend on concrete runtimes, telemetry backends, or
  eval runners.
- Compiler/runtime code may depend on declarations.
- Participant adapters may depend on declaration contracts and runtime context.
- Observability and eval systems should consume public contracts and run
  evidence.
- Third-party framework imports should stay confined to adapter modules where
  practical.

The existing import-linter contract for `pydantic_evals` is the model: keep
third-party runner dependencies out of the core framework surface.

## Current Boundaries and Future Portability

Current reality:

- LangGraph is the current compiler/runtime backend.
- Docker + Claude Code is the current `AgentAction` executor path.
- OpenTelemetry is the core telemetry substrate.
- MLflow and Pydantic Evals are current adapters, not the only intended
  backends.

The adapter ecosystem is still a work in progress. The framework should make it
possible to compare and replace volatile choices such as workflow engines,
agent harnesses, model providers, tool systems, memory strategies, and
observability backends while preserving typed process boundaries.

## Related Docs

- [Public API policy](../reference/public-api.md)
- [Runtime accessors](../reference/runtime.md)
- [Agent container reference](../reference/agent-containers.md)
- [AICall resilience reference](../reference/ai-call-resilience.md)
- [Evals reference](../reference/evals.md)
- [Observability adapter design](../design/observability-adapter-design.md)
- [Motivation and principles](motivation-and-principles.md)
