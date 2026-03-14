# Specification: Agent Foundry / Product Layer Architectural Separation

## Objective

Define the architectural boundary between Agent Foundry (reusable platform) and its product layer (Archipelago and future products). This specification establishes what Agent Foundry owns, what products own, how products consume the framework, and the phased migration plan from the current monorepo to cleanly separated packages. The end state is two independent repos -- `agent-foundry` and `archipelago` -- where Archipelago depends on Agent Foundry as a Python package, and any future product does the same.

Success looks like:

1. A developer can build a new product on Agent Foundry without reading Archipelago's code.
2. Agent Foundry can be installed as a single package with zero product-specific content.
3. Archipelago runs identically after separation -- same pipeline, same handlers, same behavior.
4. The boundary is enforced by import rules: Agent Foundry never imports from a product package.

---

## Architecture Overview

```
+------------------------------------------------------------------+
|                        Product Layer                              |
|                                                                   |
|  +---------------------------+   +---------------------------+    |
|  |       Archipelago         |   |     Future Product N      |    |
|  |  - domain models          |   |  - domain models          |    |
|  |  - handlers               |   |  - handlers               |    |
|  |  - prompts                |   |  - prompts                |    |
|  |  - wiring plans           |   |  - wiring plans           |    |
|  |  - capability specs       |   |  - capability specs       |    |
|  |  - CLI / entrypoint       |   |  - CLI / entrypoint       |    |
|  +------------+--------------+   +------------+--------------+    |
|               |                               |                   |
+------------------------------------------------------------------+
                |                               |
                v                               v
+------------------------------------------------------------------+
|                      Agent Foundry                                |
|                                                                   |
|  +-------------------+  +-------------------+  +---------------+  |
|  |    Compiler        |  |    Registry        |  | Observability |  |
|  |  compile_plan()    |  |  CapabilityRegistry|  | ExecutionTracer|  |
|  |  templates         |  |  load_spec()       |  | Span          |  |
|  |  checkpointing     |  |  execute_capability|  | eval gates    |  |
|  +-------------------+  |  auto-load builtins |  +---------------+  |
|                          +-------------------+                     |
|  +-------------------+  +-------------------+  +---------------+  |
|  |    Planner         |  |    Retriever       |  |   Runtime     |  |
|  |  validate_plan()   |  |  FAISS indexer     |  | schema enforce|  |
|  |  plan schema       |  |  retrieval         |  | retries/timeout|  |
|  |  (NO goal maps)    |  |                    |  | handler import |  |
|  +-------------------+  +-------------------+  +---------------+  |
|                                                                   |
|  Built-in Capability Specs (auto-loaded from package resources):  |
|  schema_validator, citation_validator, uncertainty_completeness_, |
|  evidence_first_contract, rag_retriever, structured_output_,     |
|  tool_calling, human_approval_gate                                |
+------------------------------------------------------------------+
                |
                v
+------------------------------------------------------------------+
|                     Infrastructure                                |
|  LangGraph | LangChain | Pydantic | jsonschema | FAISS           |
+------------------------------------------------------------------+
```

**Key rules:**

- Arrows point downward only. A lower layer never imports from a higher layer.
- Agent Foundry has no knowledge of any product. It exports composable primitives.
- Products depend on `agent_foundry` as a Python package dependency.
- Each product is independently installable and runnable.

---

## Agent Foundry Package Boundaries

### What stays in `agent_foundry`

Organized by current module path. Each item lists the specific files and what they provide.

#### `agent_foundry.compiler`

| File           | Contents                                                                                                                                   | Status      |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ----------- |
| `compiler.py`  | `compile_plan()`, handler resolution, checkpointing, eval gate enforcement, iteration limiting, conditional routing                        | Stays as-is |
| `errors.py`    | `PlanCompilationError`, `CapabilityInstantiationError`, `MaxIterationsExceededError`                                                       | Stays as-is |
| `templates.py` | `expand_template()` with built-in patterns (`draft_review_revise_loop`, `gather_verify_analyze_recommend`, `plan_execute_test_fix_retest`) | Stays as-is |

#### `agent_foundry.planner`

| File             | Contents                                                                                           | Status                           |
| ---------------- | -------------------------------------------------------------------------------------------------- | -------------------------------- |
| `wiring_plan.py` | `GraphWiringPlan`, `NodeDef`, `EdgeDef`, `ToolDef`, `PersistenceConfig`                            | Stays as-is                      |
| `validators.py`  | `validate_plan()` with 7 structural checks                                                         | Stays as-is                      |
| `errors.py`      | All planner exception types                                                                        | Stays as-is                      |
| `planner.py`     | `WiringPlanner` class, `_GOAL_PLANS`, `_DECISION_SUPPORT_PLAN`, `_ARCHIPELAGO_PIPELINE_PLAN`, etc. | **Changes required** (see below) |

**Changes to `planner.py`:**

The `WiringPlanner` with its hardcoded `_GOAL_PLANS` dictionary is removed entirely. Products author their own wiring plans as static data (JSON/YAML files or Python dicts). Agent Foundry provides:

- The plan schema: `GraphWiringPlan` and its component models
- Plan validation: `validate_plan()`
- Plan compilation: `compile_plan()`
- Plan templates: `expand_template()`

The `_DECISION_SUPPORT_PLAN` and `_DECISION_SUPPORT_WITH_TOOLS_PLAN` move into the demo product (or are removed if the demo is retired). The `_ARCHIPELAGO_PIPELINE_PLAN` moves into Archipelago's repo.

What remains in planner.py after removal of `WiringPlanner`:

```python
# agent_foundry/planner/planner.py -- after separation
# This file may be deleted entirely, or kept for future framework-level
# planning utilities (e.g., LLM-backed plan generation).
# For now: empty or deleted. All exports come from wiring_plan.py and validators.py.
```

#### `agent_foundry.registry`

| File | Contents | Status |
|---|---|---|
| `registry.py` | `CapabilityRegistry` with `from_directory()`, `get()`, `names()`, `search()` | **Changes required** (see Registry Auto-Loading) |
| `spec.py` | `CapabilitySpec`, `ImplementationPointer`, `QualityControls`, `load_capability_spec()` | Stays as-is |
| `execution.py` | `execute_capability()` with schema enforcement, retries, timeouts | Stays as-is |
| `imports.py` | `import_capability_class()`, `resolve_handler_callable()` | Stays as-is |
| `errors.py` | All registry exception types | Stays as-is |

#### `agent_foundry.observability`

| File | Contents | Status |
|---|---|---|
| `tracer.py` | `ExecutionTracer`, `Span`, redaction utilities | Stays as-is |
| `gates.py` | `schema_validator_gate()`, `citation_validator_gate()`, `uncertainty_completeness_gate()`, `evidence_first_gate()` | Stays as-is |

#### `agent_foundry.retriever`

| File | Contents | Status |
|---|---|---|
| `indexer.py` | FAISS indexing | Stays as-is |
| `retrieval.py` | Retrieval logic | Stays as-is |
| `errors.py` | Retriever exceptions | Stays as-is |

#### `agent_foundry.demo` (decision)

The demo runner (`demo/runner.py`, `demo/cli.py`) is a product-like example that lives in Agent Foundry. Two options:

1. **Keep it as an in-repo example** under `examples/decision_support/` -- useful for integration tests and documentation.
2. **Remove it** and let each product serve as its own example.

**Decision: Keep as `examples/` directory.** It serves as the canonical "how to use Agent Foundry" reference. It must NOT be part of the installable package -- it lives outside `src/agent_foundry/`.

#### Built-in capability specs

These YAML files ship with the `agent_foundry` package as package data:

```
src/agent_foundry/capabilities/
    schema_validator.yaml
    citation_validator.yaml
    uncertainty_completeness_validator.yaml
    evidence_first_contract.yaml
    rag_retriever.yaml
    tool_calling.yaml
    human_approval_gate.yaml
    structured_output_pydantic.yaml
```

These are auto-loaded by the registry (see Registry Auto-Loading section).

### What moves out of `agent_foundry`

| Current location | Destination | What |
|---|---|---|
| `src/agent_foundry/planner/planner.py` (`_ARCHIPELAGO_PIPELINE_PLAN`) | `archipelago` repo | Archipelago's pipeline plan definition |
| `src/agent_foundry/planner/planner.py` (`_DECISION_SUPPORT_PLAN`, `_DECISION_SUPPORT_WITH_TOOLS_PLAN`) | `examples/decision_support/` | Demo plans |
| `src/agent_foundry/planner/planner.py` (`WiringPlanner` class) | Deleted | Products own their plans |
| `src/archipelago/capabilities/strategy_generate_product_brief.yaml` | in `archipelago` repo | Archipelago capability spec |
| `src/archipelago/capabilities/architecture_generate_feature_arch.yaml` | in `archipelago` repo | Archipelago capability spec |
| `src/archipelago/capabilities/spec_generate_feature_spec.yaml` | in `archipelago` repo | Archipelago capability spec |
| `src/archipelago/capabilities/dev_implement_feature_tdd.yaml` | in `archipelago` repo | Archipelago capability spec |
| `src/archipelago/capabilities/coding_implement_feature_from_spec.yaml` | in `archipelago` repo | Archipelago capability spec |
| `src/archipelago/` (entire package) | `archipelago` repo | Product code |

---

## Product Layer Contract

Products consume Agent Foundry through a well-defined API. Here is the concrete pattern every product follows.

### 1. Install Agent Foundry

```toml
# archipelago/pyproject.toml
[project]
name = "archipelago"
dependencies = [
    "agent-foundry>=0.2.0,<1.0.0",
    "langchain-anthropic>=1.3.4",
]
```

### 2. Define domain models

```python
# archipelago/models.py
from pydantic import BaseModel

class ProductBrief(BaseModel):
    name: str
    problem_statement: str
    target_personas: list[str]
    success_metrics: list[str]
    constraints: list[str] = []
```

### 3. Write capability specs

```yaml
# archipelago/capabilities/strategy_generate_product_brief.yaml
name: strategy_generate_product_brief
description: Generates a product brief from high-level input
version: "1.0.0"
implementation:
  module: archipelago.handlers
  class_name: StrategyHandler
inputs_schema:
  type: object
  properties:
    product_brief_input:
      type: string
  required: [product_brief_input]
outputs_schema:
  type: object
  properties:
    product_brief:
      type: object
  required: [product_brief]
tags: [archipelago, strategy, generation]
quality_controls:
  timeout_seconds: 120
  max_retries: 1
```

### 4. Implement handlers

Handlers follow the universal signature: `(state: dict[str, Any]) -> dict[str, Any]`.

```python
# archipelago/handlers.py
from typing import Any
from langchain_anthropic import ChatAnthropic
from archipelago.models import ProductBrief
from archipelago.prompts import STRATEGY_PROMPT

def strategy_handler(state: dict[str, Any]) -> dict[str, Any]:
    llm = ChatAnthropic(model="claude-sonnet-4-20250514").with_structured_output(ProductBrief)
    prompt = STRATEGY_PROMPT.format(product_brief_input=state["product_brief_input"])
    result = llm.invoke([HumanMessage(content=prompt)])
    return {**state, "product_brief": result.model_dump()}
```

### 5. Author a wiring plan

Products define their wiring plans as data. Two options:

**Option A: JSON file (recommended for most cases)**

```json
// archipelago/archipelago_system.json
{
  "goal": "archipelago-pipeline",
  "nodes": [
    {"id": "strategy", "capability": "strategy_generate_product_brief", "config": {}},
    {"id": "architecture", "capability": "architecture_generate_feature_arch", "config": {}},
    {"id": "spec", "capability": "spec_generate_feature_spec", "config": {}},
    {"id": "spec_approval_gate", "capability": "human_approval_gate", "config": {}},
    {"id": "dev_test", "capability": "coding_implement_feature_from_spec", "config": {}}
  ],
  "edges": [
    {"source": "strategy", "target": "architecture"},
    {"source": "architecture", "target": "spec"},
    {"source": "spec", "target": "spec_approval_gate"},
    {"source": "spec_approval_gate", "target": "dev_test"}
  ],
  "entry_point": "strategy",
  "breakpoints": ["spec_approval_gate"],
  "capability_versions": {
    "strategy_generate_product_brief": "1.0.0",
    "architecture_generate_feature_arch": "1.0.0",
    "spec_generate_feature_spec": "1.0.0",
    "human_approval_gate": "1.0.0",
    "coding_implement_feature_from_spec": "1.0.0"
  }
}
```

Agent Foundry provides a loader for this:

```python
from agent_foundry.planner.wiring_plan import GraphWiringPlan

plan = GraphWiringPlan.from_json("archipelago_system.json")
```

**Option B: Python dict (useful when plans are computed or composed programmatically)**

```python
# archipelago/pipeline.py
from agent_foundry.planner.wiring_plan import GraphWiringPlan

PIPELINE_PLAN = GraphWiringPlan(
    goal="archipelago-pipeline",
    nodes=[
        {"id": "strategy", "capability": "strategy_generate_product_brief", "config": {}},
        {"id": "architecture", "capability": "architecture_generate_feature_arch", "config": {}},
        {"id": "spec", "capability": "spec_generate_feature_spec", "config": {}},
        {"id": "spec_approval_gate", "capability": "human_approval_gate", "config": {}},
        {"id": "dev_test", "capability": "coding_implement_feature_from_spec", "config": {}},
    ],
    edges=[
        {"source": "strategy", "target": "architecture"},
        {"source": "architecture", "target": "spec"},
        {"source": "spec", "target": "spec_approval_gate"},
        {"source": "spec_approval_gate", "target": "dev_test"},
    ],
    entry_point="strategy",
    breakpoints=["spec_approval_gate"],
    capability_versions={
        "strategy_generate_product_brief": "1.0.0",
        "architecture_generate_feature_arch": "1.0.0",
        "spec_generate_feature_spec": "1.0.0",
        "human_approval_gate": "1.0.0",
        "coding_implement_feature_from_spec": "1.0.0",
    },
)
```

### 6. Build a registry and compile

```python
# archipelago/runner.py
from pathlib import Path
from typing import Any

from agent_foundry.registry.registry import CapabilityRegistry
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.planner.validators import validate_plan
from agent_foundry.compiler.compiler import compile_plan

HANDLER_REGISTRY = {
    "strategy_generate_product_brief": strategy_handler,
    "architecture_generate_feature_arch": architecture_handler,
    "spec_generate_feature_spec": spec_handler,
    "human_approval_gate": spec_approval_gate_handler,
    "coding_implement_feature_from_spec": dev_test_handler,
}

def run(product_brief_input: str) -> dict[str, Any]:
    # Load plan from JSON file
    plan = GraphWiringPlan.from_json(Path(__file__).parent / "archipelago_system.json")

    # Registry auto-loads Agent Foundry builtins.
    # Product adds its own specs on top.
    registry = CapabilityRegistry.with_product_specs(
        Path(__file__).parent / "capabilities"
    )

    validate_plan(plan, registry)

    graph = compile_plan(
        plan,
        registry,
        handler_registry=HANDLER_REGISTRY,
    )

    return graph.invoke({"product_brief_input": product_brief_input})
```

### The import rule

Products import from `agent_foundry`. Agent Foundry never imports from a product.

```
ALLOWED:
    from agent_foundry.planner.wiring_plan import GraphWiringPlan
    from agent_foundry.compiler.compiler import compile_plan
    from agent_foundry.registry.registry import CapabilityRegistry

FORBIDDEN (inside agent_foundry):
    from archipelago.models import ProductBrief
    from archipelago.handlers import strategy_handler
```

This is enforced by CI lint rules (import-linter or similar) once repos are split.

---

## Registry Auto-Loading

### Current behavior

`CapabilityRegistry.from_directory(path)` scans a single directory for YAML/JSON files. Products and framework specs are mixed together in `capabilities/`.

### Target behavior

The registry auto-loads Agent Foundry's built-in capability specs from package resources. Products add their own specs on top.

### Implementation

Add a class method to `CapabilityRegistry`:

```python
# agent_foundry/registry/registry.py

import importlib.resources

BUILTIN_SPECS_PACKAGE = "agent_foundry.capabilities"


class CapabilityRegistry:
    # ... existing methods ...

    @classmethod
    def with_builtins(cls) -> "CapabilityRegistry":
        """Create a registry pre-loaded with Agent Foundry's built-in specs."""
        specs = _load_builtin_specs()
        return cls(specs)

    @classmethod
    def with_product_specs(
        cls,
        product_specs_dir: Path,
    ) -> "CapabilityRegistry":
        """Create a registry with builtins + product-specific specs.

        Args:
            product_specs_dir: Directory containing the product's YAML/JSON
                               capability spec files.

        Returns:
            A registry containing both built-in and product specs.

        Raises:
            DuplicateCapabilityError: If a product spec collides with a builtin name.
        """
        builtin_specs = _load_builtin_specs()
        product_specs = _load_directory_specs(product_specs_dir)

        # Check for collisions
        for name in product_specs:
            if name in builtin_specs:
                raise DuplicateCapabilityError(
                    message=f"Product spec '{name}' collides with built-in spec",
                    capability_name=name,
                    file_paths=[],
                )

        combined = {**builtin_specs, **product_specs}
        return cls(combined)

    @classmethod
    def from_directory(cls, directory: Path) -> "CapabilityRegistry":
        """Load specs from a single directory (legacy behavior, no auto-loading)."""
        # ... existing implementation unchanged for backward compat ...


def _load_builtin_specs() -> dict[str, CapabilitySpec]:
    """Load built-in specs from agent_foundry.capabilities package data."""
    specs: dict[str, CapabilitySpec] = {}
    files = importlib.resources.files(BUILTIN_SPECS_PACKAGE)
    for item in files.iterdir():
        if item.name.endswith((".yaml", ".yml", ".json")):
            text = item.read_text()
            # Parse and validate (reuse existing parsing logic)
            ...
    return specs
```

### Spec packaging

The built-in YAML files must be included in the `agent_foundry` package distribution:

```toml
# pyproject.toml for agent-foundry
[tool.setuptools.package-data]
"agent_foundry" = ["capabilities/*.yaml"]
```

Or with PDM/hatchling:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/agent_foundry"]

# Ensure capabilities/ is inside the package:
# src/agent_foundry/capabilities/*.yaml
```

### Migration path

1. Move the 8 framework YAML files from `capabilities/` (repo root) into `src/agent_foundry/capabilities/`.
2. Add `__init__.py` to `src/agent_foundry/capabilities/` (empty, needed for `importlib.resources`).
3. Add `with_builtins()` and `with_product_specs()` to `CapabilityRegistry`.
4. Keep `from_directory()` as-is for backward compatibility during migration.
5. Update demo runner and tests to use new methods.
6. Product repos use `with_product_specs()` pointing at their local `capabilities/` dir.

---

## Capability Spec Classification

### Current inventory (13 specs)

**Framework-level (8)** -- stay in `src/agent_foundry/capabilities/`:

| Spec name                            | Rationale                                              |
| ------------------------------------ | ------------------------------------------------------ |
| `schema_validator`                   | Generic schema validation gate; any product can use it |
| `citation_validator`                 | Generic citation checking gate                         |
| `uncertainty_completeness_validator` | Generic uncertainty/completeness check                 |
| `evidence_first_contract`            | Generic evidence-first enforcement                     |
| `rag_retriever`                      | Generic RAG retrieval node                             |
| `tool_calling`                       | Generic tool execution node                            |
| `human_approval_gate`                | Generic human-in-the-loop gate                         |

**Removed as capability (1)** -- becomes an implemented best practice:

| Spec name                    | Rationale                                              |
| ---------------------------- | ------------------------------------------------------ |
| `structured_output_pydantic` | Not a discrete capability. Structured output via Pydantic is a pattern that every LLM-calling handler should use inline (e.g., `llm.with_structured_output(MyModel)`). Agent Foundry documents this as a best practice and may provide a utility helper, but it does not belong as a node in a wiring plan. The capability spec is deleted. |

**Product-level (5)** -- move to Archipelago repo:

| Spec name | Rationale |
|---|---|
| `strategy_generate_product_brief` | Archipelago-specific pipeline stage |
| `architecture_generate_feature_arch` | Archipelago-specific pipeline stage |
| `spec_generate_feature_spec` | Archipelago-specific pipeline stage |
| `dev_implement_feature_tdd` | Archipelago-specific pipeline stage |
| `coding_implement_feature_from_spec` | Archipelago-specific pipeline stage |

### Classification rule for future specs

**Framework-level** if ALL of the following are true:

1. The capability is domain-agnostic (not tied to any specific product's problem space).
2. At least two products would benefit from it, or it provides a foundational primitive (gate, retrieval, structured output, etc.).
3. Its I/O schema uses generic structures, not product-specific domain models.

**Product-level** if ANY of the following are true:

1. The capability's I/O schema references product-specific domain models.
2. The capability implements business logic specific to one product.
3. The capability's prompts contain product-specific instructions.

When in doubt, start at the product level. Promote to framework when a second product needs the same capability -- then generalize the I/O schema.

---

## Migration Plan

Separation is done in phases. Each phase is independently mergeable. The system works after each phase.

### Phase 1: Package the built-in specs (Agent Foundry repo)

**Goal:** Move framework capability specs into the package and add auto-loading.

**Steps:**

1. Create `src/agent_foundry/capabilities/` directory with `__init__.py`.
2. Move the 7 framework YAML files from repo-root `capabilities/` into `src/agent_foundry/capabilities/`.
3. Add `with_builtins()` class method to `CapabilityRegistry`.
4. Add `with_product_specs(product_dir)` class method to `CapabilityRegistry`.
5. Add package-data configuration to `pyproject.toml`.
6. Update existing tests that use `from_directory()` on the repo-root `capabilities/` to work with the new location. Keep `from_directory()` functional for backward compat.

**Acceptance criteria:**

- Given `CapabilityRegistry.with_builtins()` is called, when `len(registry)` is checked, then it returns 7.
- Given `CapabilityRegistry.with_builtins()` is called, when `registry.get("schema_validator")` is called, then it returns a valid `CapabilitySpec`.
- Given `CapabilityRegistry.with_product_specs(product_dir)` is called with a directory containing 5 product specs, when `len(registry)` is checked, then it returns 12.
- Given a product spec has the same name as a built-in, when `with_product_specs()` is called, then `DuplicateCapabilityError` is raised.
- Given `from_directory()` is called on the old capabilities path (with all 12 remaining specs still present during transition), when `len(registry)` is checked, then it still returns 12.

**Complexity:** M

### Phase 2: Remove WiringPlanner and hardcoded goal maps (Agent Foundry repo)

**Goal:** Delete the `WiringPlanner` class and all `_GOAL_PLANS` from `planner.py`. Products own their plans.

**Steps:**

1. Move `_DECISION_SUPPORT_PLAN` and `_DECISION_SUPPORT_WITH_TOOLS_PLAN` into separate JSON files: `examples/decision_support/decision_support_plan.json` and `examples/decision_support/decision_support_with_tools_plan.json`.
2. Delete `_ARCHIPELAGO_PIPELINE_PLAN` from `planner.py` (it already exists in `src/archipelago/archipelago_system.json` in the product).
3. Delete the `WiringPlanner` class from `planner.py`.
4. Update or delete `planner.py`. If it becomes empty, delete it and adjust `__init__.py` exports.
5. Update the demo runner to load its plan from a local file instead of `WiringPlanner`.
6. Update all tests that reference `WiringPlanner` or `_GOAL_PLANS`.

**Acceptance criteria:**

- Given the `agent_foundry.planner` module, when its public exports are inspected, then `WiringPlanner` is not present.
- Given the demo runner, when it runs, then it loads its plan from a local JSON file (not from `WiringPlanner`).
- Given the Archipelago runner, when it runs, then it loads its plan from `archipelago/archipelago_system.json`.
- Given `agent_foundry.planner.planner` (if it still exists), when imported, then it contains no product-specific plan data.

**Complexity:** M

**Dependencies:** None (can be done in parallel with Phase 1)

### Phase 3: Separate Archipelago into its own package (monorepo boundary)

**Goal:** Make `src/archipelago/` a standalone package that imports from `agent_foundry`.

**Steps:**

1. Move the 5 Archipelago capability YAML files from repo-root `capabilities/` into `src/archipelago/capabilities/`.
2. Verify `src/archipelago/runner.py` uses `CapabilityRegistry.with_product_specs()` instead of `from_directory()` on the shared capabilities dir.
3. Verify all imports in `src/archipelago/` reference `agent_foundry.*` (not relative paths into `src/agent_foundry/`). This should already be the case given the current structure.
4. Add a separate `pyproject.toml` for archipelago (or configure the monorepo for multi-package).
5. Remove the Archipelago pipeline plan from anywhere inside `src/agent_foundry/`.
6. Run the full test suite to confirm no cross-boundary import violations.

**Acceptance criteria:**

- Given `src/archipelago/`, when all Python files are scanned for imports, then none import from `agent_foundry.planner.planner` (the deleted WiringPlanner module).
- Given `src/archipelago/capabilities/`, when listed, then it contains exactly the 5 Archipelago specs.
- Given `src/agent_foundry/`, when all Python files are scanned for imports, then none import from `archipelago`.
- Given the Archipelago runner, when run with `CapabilityRegistry.with_product_specs()`, then the pipeline executes correctly with all 13 capabilities available.

**Complexity:** M

**Dependencies:** Phase 1, Phase 2

### Phase 4: Enforce boundaries with linting (Agent Foundry repo)

**Goal:** Add automated enforcement of the import boundary.

**Steps:**

1. Add `import-linter` (or equivalent) to dev dependencies.
2. Configure a contract: `agent_foundry` must not import from `archipelago` (or any product package).
3. Add the lint check to CI.

**Acceptance criteria:**

- Given the CI pipeline, when a PR adds `from archipelago import X` inside `src/agent_foundry/`, then CI fails.

**Complexity:** S

**Dependencies:** Phase 3

### Phase 5: Split into separate repositories

**Goal:** Move from monorepo to two repos.

**Steps:**

1. Create `agent-foundry` repo with contents of `src/agent_foundry/`, `examples/`, framework tests, and `pyproject.toml`.
2. Create `archipelago` repo with contents of `src/archipelago/`, product tests, and its own `pyproject.toml` declaring `agent-foundry` as a dependency.
3. Set up a private PyPI index (or Git-based dependency) for `agent-foundry`.
4. Archipelago's `pyproject.toml` pins `agent-foundry>=0.2.0,<1.0.0`.
5. Remove product code from the `agent-foundry` repo.
6. CI for both repos. Archipelago's CI installs `agent-foundry` from the index.

**Acceptance criteria:**

- Given the `agent-foundry` repo, when `pdm install` is run, then no product code is present.
- Given the `archipelago` repo, when `pdm install` is run, then `agent-foundry` is installed as a dependency.
- Given the `archipelago` test suite, when run against the installed `agent-foundry` package, then all tests pass.

**Complexity:** L

**Dependencies:** Phase 4

---

## Public API Surface

Agent Foundry guarantees the following as its stable public API. These are the imports that products rely on. Breaking changes to these require a semver MINOR bump (pre-1.0) or MAJOR bump (post-1.0).

### Plan schema

```python
from agent_foundry.planner.wiring_plan import (
    GraphWiringPlan,       # includes .from_json(path) class method
    NodeDef,
    EdgeDef,
    ToolDef,
    PersistenceConfig,
)
```

### Plan validation

```python
from agent_foundry.planner.validators import validate_plan
```

### Plan validation errors

```python
from agent_foundry.planner.errors import (
    PlanValidationError,
    DuplicateNodeIdError,
    UnknownCapabilityError,
    DanglingEdgeError,
)
```

### Compilation

```python
from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.compiler.templates import expand_template
from agent_foundry.compiler.errors import (
    PlanCompilationError,
    CapabilityInstantiationError,
)
```

### Registry

```python
from agent_foundry.registry.registry import CapabilityRegistry
from agent_foundry.registry.spec import (
    CapabilitySpec,
    ImplementationPointer,
    QualityControls,
    load_capability_spec,
)
from agent_foundry.registry.execution import execute_capability
from agent_foundry.registry.imports import (
    import_capability_class,
    resolve_handler_callable,
)
from agent_foundry.registry.errors import (
    CapabilitySpecValidationError,
    CapabilitySpecParseError,
    DuplicateCapabilityError,
    CapabilityImportError,
    CapabilityExecutionError,
)
```

### Observability

```python
from agent_foundry.observability.tracer import ExecutionTracer, Span
from agent_foundry.observability.gates import (
    schema_validator_gate,
    citation_validator_gate,
    uncertainty_completeness_gate,
    evidence_first_gate,
)
```

### Retriever

```python
from agent_foundry.retriever.indexer import ...   # TBD: document specific exports
from agent_foundry.retriever.retrieval import ... # TBD: document specific exports
```

### Handler protocol

The handler signature is the core contract between Agent Foundry and product code:

```python
# Any callable matching this signature works as a handler:
def handler(state: dict[str, Any]) -> dict[str, Any]: ...
```

Agent Foundry does not require handlers to inherit from a base class. Any callable matching the signature works. This is the composition-over-inheritance principle in action.

### Handler registry protocol

```python
# A plain dict mapping capability names to handler functions:
handler_registry: dict[str, Callable[[dict[str, Any]], dict[str, Any]]]
```

### Feature flags

Feature flags (`FF_COMPILER`, `FF_TRACING`, `FF_SCHEMA_ENFORCEMENT`, etc.) are module-level booleans. They are NOT part of the public API. Products should not depend on or toggle them. They exist for internal development gating.

### Versioning

- Pre-1.0: MINOR bumps may contain breaking changes to the public API (with changelog entries).
- Post-1.0: Standard semver. PATCH for bug fixes, MINOR for backward-compatible additions, MAJOR for breaking changes.
- Internal-only period (next 6-24 months): Semver is advisory. Breaking changes are coordinated directly with product teams.

---

## Open Questions

1. **Demo runner disposition.** Should the decision-support demo stay in the Agent Foundry repo as `examples/` or move to its own repo? Current recommendation: keep as `examples/` for now because it serves as integration test and usage documentation. Revisit if it becomes a maintenance burden.

2. **Built-in handler implementations.** The 8 framework capability specs point to handler implementations via `ImplementationPointer`. Where do these handler classes live? Options:
   - Inside `agent_foundry` as default implementations (recommended -- they are reusable primitives).
   - As abstract specs with no implementation (products always provide their own handler via `handler_registry`).

   Current state: most framework specs point to handler classes that don't exist yet (the demo uses `handler_registry` overrides). This needs resolution before the built-in specs are meaningful as auto-loaded defaults.

3. **Private PyPI vs Git dependency.** For the repo split (Phase 5), how does Archipelago install Agent Foundry?
   - Private PyPI index (Artifactory, CodeArtifact, or similar)
   - Git dependency (`agent-foundry @ git+ssh://...`)
   - Path dependency during development (`agent-foundry @ file:///...`)

   Recommendation: Git dependency for initial split, private PyPI once there are 3+ consumers.

4. **Capability spec versioning across repos.** When Agent Foundry bumps a built-in spec's version (e.g., `human_approval_gate` from `1.0.0` to `1.1.0`), products must update their `capability_versions` in wiring plans. How is this coordinated?
   - `validate_plan()` already checks version coverage -- but it doesn't enforce version compatibility ranges.
   - Consider adding an optional `min_version` / `max_version` check in validation.

5. **Plan template ownership.** The current templates in `compiler/templates.py` (`draft_review_revise_loop`, etc.) are framework-level. Should products be able to register their own templates? Current recommendation: no. Products just define their plans directly. Templates are a framework convenience, not a plugin system.

6. **Test infrastructure sharing.** Some test fixtures (e.g., `CAPABILITIES_DIR`, stub handlers) are useful to both framework tests and product tests. Should Agent Foundry export test utilities?
   - Option A: `agent_foundry.testing` module with shared fixtures (e.g., `make_stub_registry()`, `make_passthrough_handler()`).
   - Option B: Each repo duplicates what it needs.

   Recommendation: Add `agent_foundry.testing` as a lightweight module. Mark it clearly as not part of the runtime public API.

7. **`from_directory()` deprecation timeline.** Once `with_builtins()` and `with_product_specs()` are stable, should `from_directory()` be deprecated? It remains useful for testing (loading specs from a temp dir). Recommendation: keep it indefinitely as a low-level utility, but document that `with_product_specs()` is the preferred entry point for products.
