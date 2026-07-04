# Evals Reference

Agent Foundry includes a typed eval subsystem for scoring `AICall` and
`AgentAction` behavior against curated datasets.

The eval system follows the same portability strategy as the rest of Agent
Foundry: suite definitions and reports are Agent Foundry Pydantic models, while
third-party eval frameworks live behind runner adapters.

## Current Scope

- Declarative suite models: `EvalSuite`, `Dataset`, `Case`, evaluator specs, and
  report types.
- Target types:
  - `AICallTarget` for direct model-call evaluation.
  - `AgentTarget` for full orchestration-path agent evaluation.
- Runner protocol with an initial Pydantic-Evals-backed runner.
- `AICallRegistry` for explicitly exposing model calls to eval tooling.
- CLI and HTTP API entry points.
- JSON report persistence.

## Key Modules

| Module | Purpose |
|--------|---------|
| `agent_foundry.evals` | Public eval models, target registry, and task builders. |
| `agent_foundry.evals.models` | Pydantic suite, target, evaluator, runner, and report models. |
| `agent_foundry.evals.registry` | `AICallRegistry` opt-in target registry. |
| `agent_foundry.evals.runner_loader` | Dynamic `module:Class` runner loading. |
| `agent_foundry.evals.runners.pydantic_evals` | Initial Pydantic-Evals runner adapter. |
| `agent_foundry.evals.cli` | CLI entry point for suite execution. |
| `agent_foundry.evals.api` | FastAPI target-discovery API. |

## Runner Boundary

Only runner adapter modules should import third-party eval frameworks. The rest
of Agent Foundry should depend on the internal Pydantic contracts.

The current import-linter contract forbids `pydantic_evals` imports outside
`agent_foundry.evals.runners.pydantic_evals`.

## Configure The API

Place `agent_foundry.config` at the application root:

```toml
registry = "your_app.evals.registration:EVAL_REGISTRY"

[api]
host = "127.0.0.1"
port = 8000
```

The registry value is a `module:attribute` string pointing at an
`AICallRegistry`.

## Register AICalls

```python
from agent_foundry.evals import AICallRegistry
from your_app.ai_calls import design_review

EVAL_REGISTRY = AICallRegistry()
EVAL_REGISTRY.register("design_review", design_review)
```

Unregistered calls are invisible to the eval API.

## Define A Suite

```python
from agent_foundry.evals import (
    AICallTarget,
    Case,
    Dataset,
    EqualsExpectedSpec,
    EvalSuite,
)
from your_app.ai_calls import design_review

suite = EvalSuite(
    name="design_review_v1",
    target=AICallTarget(ai_call=design_review),
    dataset=Dataset(
        name="design_review_cases_v1",
        cases=[
            Case(name="good", inputs=..., expected_output=...),
        ],
        evaluators=[EqualsExpectedSpec()],
    ),
    invocations_per_case=3,
)
```

## Run A Suite

```bash
pdm run python -m agent_foundry.evals.cli path/to/suite.py \
    --out-dir ./eval-runs
```

Reports are written to:

```text
eval-runs/<run_id>/report.json
```

## Run The API

```bash
pdm run eval-api
curl http://127.0.0.1:8000/targets
curl http://127.0.0.1:8000/targets/design_review
```

The current API supports target discovery. Additional run-management endpoints
are future work.
