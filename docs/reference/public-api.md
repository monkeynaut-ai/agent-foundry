# Public API Policy

Agent Foundry is pre-1.0. APIs can still change, but the project should make
clear which import paths builders can rely on and which paths are implementation
details.

This policy applies to documented Python imports, public lifecycle/artifact
contracts, and extension seams.

## API Tiers

### Stable Public

Stable public APIs are the preferred surface for application code, examples,
guides, and third-party extensions.

Current stable public surfaces:

- `agent_foundry`
- `agent_foundry.constructs`
- `agent_foundry.compiler`
- `agent_foundry.ai_models`
- `agent_foundry.evals`
- `agent_foundry.responders`
- `agent_foundry.telemetry`
- selected `agent_foundry.orchestration` exports:
  - `run_process`
  - run outcome types
  - lifecycle event names

Rules:

- Symbols exported through `__all__` and documented in guides/reference docs are
  considered public.
- Backward-incompatible changes should be called out in release notes.
- Prefer adding new symbols over changing existing constructor or method
  behavior in surprising ways.
- Deprecate before removing when practical.

### Experimental Public

Experimental public APIs are documented and importable, but their shape may
change while the framework pivot settles.

Current experimental public surfaces:

- `agent_foundry.orchestration.run_agent_in_container`
- `agent_foundry.orchestration.RunContext`
- run hook event types from `agent_foundry.orchestration`
- `agent_foundry.mlflow_adapter`
- container-specific configuration and execution behavior
- adapter-specific continuation, artifact, and telemetry behavior

Rules:

- Experimental APIs may change before 1.0 without a long deprecation window.
- Docs should label experimental surfaces as adapter-specific or current-scope
  when appropriate.
- Tests should still cover the behavior Agent Foundry currently documents.

### Internal

Internal APIs are implementation details. Application code should not rely on
them.

Examples:

- underscored helpers
- deep compiler helper functions
- container registry internals
- lifecycle writer implementation details
- artifact helper functions
- runner internals not exported from package `__init__` modules
- modules under `agent_foundry.evals.runners`
- direct imports from implementation modules when a package-level export exists

Rules:

- Internal APIs may change without deprecation.
- Tests may import internals when testing internals, but docs and examples
  should not.
- If a doc needs an internal import, either promote the symbol intentionally or
  mark the section as implementation detail.

## Import Guidance

Use the highest-level import that communicates the intended stability:

```python
from agent_foundry import FunctionAction, Process, Sequence, run_process
from agent_foundry.ai_models import InferenceProvider, ModelEntry, register_model
from agent_foundry.compiler import CompileContext, CompileResult, register_compiler
from agent_foundry.evals import AICallRegistry, EvalSuite
```

Avoid deep imports in application code when a public package export exists:

```python
# Avoid in docs and application code when package exports exist.
from agent_foundry.compiler.compiler import CompileContext
from agent_foundry.evals.models import EvalSuite
```

## Promotion Criteria

An internal or experimental API can become stable when:

- it supports a core framework use case
- at least one guide or reference doc needs it
- tests pin the public import path
- naming and behavior match the framework vocabulary
- adapter-specific assumptions are either removed or clearly isolated

## Deprecation

Before 1.0, Agent Foundry may make breaking changes more freely, but public
changes should still be explicit.

After 1.0, stable public API removals should generally follow this path:

1. Add a replacement.
2. Document the migration.
3. Emit a deprecation warning when practical.
4. Remove in a later minor or major release according to the project's release
   policy.

Experimental APIs may use a shorter path, but changes should still be recorded
in release notes.
