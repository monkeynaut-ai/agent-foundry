# Plan: Strict Typing and Agent Decoupling

## Context

Archipelago's development velocity is bottlenecked by a coherence problem: data schemas are defined in 3 disconnected places (Pydantic models, JSON Schema in wiring plans, agent instruction markdown), and all must be manually synchronized when anything changes. Agents are also coupled to LangGraph — they receive full state dicts and return `{**state, ...updates}`.

**Goals:**
1. **Strict typing** — Pydantic models with type aliases and descriptions as single source of truth
2. **Decouple agents from orchestration** — agents declare typed parameters and return typed output models; a connector handles the LangGraph dict boundary

**Design decisions:**
- Constructor injection for static agent config (sourced from `NodeDef.config` in wiring plan)
- Composable inputs: agents declare individual typed parameters on `__call__` (not per-agent input wrapper models)
- Per-agent output models: agents return a Pydantic model wrapping their return values
- System definition declares fine-grained types by name for both inputs and outputs: `"inputs": ["CurrentTask", "WorkSpace"], "outputs": ["AgentWorkerResult", "WorkSpace", "CommitHash"]`
- No type registry — `__call__` parameter names map directly to state keys; output model field names map directly to state keys; compiler validates system definition type names against agent annotations via string matching
- Connector is LangGraph-specific, not a generic abstraction

---

## Phase 1 — Type Aliases and Model Enrichment (archipelago)

**PR 1: Typed models as single source of truth**

Pure additive, zero behavioral change.

### Commit 1a: Type aliases module

Create `src/archipelago/types.py`:
```python
from typing import TypeAlias

WorkSpace: TypeAlias = str        # Docker volume name
CommitHash: TypeAlias = str       # Git SHA
RepoUrl: TypeAlias = str          # Git remote URL
RepoRef: TypeAlias = str          # Branch or tag
Objective: TypeAlias = str        # Human-readable job objective
```

### Commit 1b: Enrich existing models with aliases and descriptions

Update `src/archipelago/models.py`:
- Replace bare `str` with type aliases
- Add `Field(description=...)` to every field in `KernelState`, `CurrentTask`, `JobDefinition`

Update `src/archipelago/docker_worker/models.py`:
- Apply type aliases and descriptions to `WorkerInput`, `WorkerConstraints`

### Commit 1c: AgentWorkerResult typed model

Add to `src/archipelago/models.py`:
```python
class AgentWorkerResult(BaseModel):
    result_summary: str = Field(description="Human-readable summary of agent execution")
    status: Literal["completed", "failed"] = Field(description="Terminal status")
    output_lines: list[str] = Field(default_factory=list, description="Raw output from agent")
    review: dict[str, Any] | None = Field(default=None, description="Parsed CodeReview (reviewer only)")
```

Update `KernelState.worker_result` from `dict[str, Any] | None` to `AgentWorkerResult | None`.

### Commit 1d: Per-agent output models

Create `src/archipelago/agents/io_models.py`:
```python
class UnitTestWriterOutput(BaseModel):
    worker_result: AgentWorkerResult
    workspace_volume: WorkSpace

class CodeWriterOutput(BaseModel):
    worker_result: AgentWorkerResult
    workspace_volume: WorkSpace
    commit_hash: CommitHash

class SoftwareReviewerOutput(BaseModel):
    worker_result: AgentWorkerResult
    workspace_volume: WorkSpace

class EvaluatorOutput(BaseModel):
    commit_passed: bool

class DecomposerOutput(BaseModel):
    objective: Objective
    repo_url: RepoUrl
    repo_ref: RepoRef
    constraints: list[str]
    commit_slices: list[dict[str, Any]]
    current_index: int

class DispatcherOutput(BaseModel):
    current_task: CurrentTask
    current_index: int
    has_more_commits: bool
```

### Commit 1e: Tests

- Each output model constructs from the dicts currently returned by agents
- `AgentWorkerResult` validates the dicts currently built in `_map_output`
- Roundtrip: `model.model_dump()` produces same shape agents currently return
- `model_json_schema()` produces valid JSON Schema

**Files:**
- New: `src/archipelago/types.py`, `src/archipelago/agents/io_models.py`
- Modify: `src/archipelago/models.py`, `src/archipelago/docker_worker/models.py`
- New: `tests/archipelago/unit/test_io_models.py`

---

## Phase 2 — TypedAgent Protocol and Connector (agent-foundry)

**PR 2: Framework support for decoupled typed agents**

Can proceed in parallel with Phase 1. Fully additive — existing dict-based agents unchanged.

### Commit 2a: TypedAgent protocol

Create `src/agent_foundry/agents/protocol.py`:

The protocol defines what a typed agent looks like:
- `__call__` takes individually typed parameters (connector discovers them via `get_type_hints()`)
- Returns a Pydantic output model
- No class attributes needed for input types — the `__call__` signature is the contract

### Commit 2b: LangGraph connector

Create `src/agent_foundry/agents/connector.py`:

```python
def make_typed_connector(agent) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Wrap a typed agent into a dict->dict callable for LangGraph.

    Inputs:
    - Inspects agent.__call__ signature for parameter names and types
    - For each parameter, extracts state[param_name]
    - If param type is a BaseModel subclass, validates via model_validate()
    - If param type is a primitive/TypeAlias, passes directly

    Outputs:
    - Calls agent(**typed_kwargs)
    - Agent returns a Pydantic output model
    - Calls output.model_dump() to produce dict for LangGraph
    """
```

### Commit 2c: Constructor injection

Modify `src/agent_foundry/registry/imports.py`:
- `resolve_typed_handler(pointer, spec, node_config)` — instantiates agent with `node_config` splatted into constructor
- Config source: `NodeDef.config` from wiring plan JSON, passed at instantiation not per-call

### Commit 2d: Compiler integration

Modify `src/agent_foundry/compiler/compiler.py`:
- Detect typed agents (have typed `__call__` parameters and return a BaseModel)
- Wrap with `make_typed_connector()`, skip `_make_config_provider`
- Fall through to existing path for dict-based agents

### Commit 2e: Update NodeDef for type-based I/O

Modify `src/agent_foundry/planner/wiring_plan.py`:
- Add optional `inputs: list[str]` and `outputs: list[str]` on `NodeDef`
- These are type names (e.g., `["CurrentTask", "WorkSpace"]`)
- Existing `inputs_schema` / `outputs_schema` remain for backward compat

### Commit 2f: Compiler validation of system definition types

The compiler validates that:
- Each type name in a node's `inputs` list matches a parameter type annotation on the agent's `__call__`
- Each type name in a node's `outputs` list matches a field type annotation on the agent's output model
- Validation is string matching on type names, no import resolution needed

### Commit 2g: Tests

- Connector roundtrip: dict -> typed params -> agent -> output model -> dict
- Handles BaseModel and TypeAlias params
- Clear errors for missing state keys
- Compiler validates type names against agent annotations
- Compiler rejects mismatched type declarations
- Backward compat: existing dict handler works identically

**Files:**
- New: `src/agent_foundry/agents/protocol.py`, `src/agent_foundry/agents/connector.py`
- Modify: `src/agent_foundry/registry/imports.py`, `src/agent_foundry/compiler/compiler.py`
- Modify: `src/agent_foundry/planner/wiring_plan.py`
- New: `tests/agent_foundry/test_typed_agent.py`, `tests/agent_foundry/test_connector.py`

---

## Phase 3 — Migrate Archipelago Agents (archipelago)

**PR 3: Agents declare typed parameters and return output models**

Requires Phase 1 + 2. One agent per commit.

### Migration pattern

**Before:**
```python
class CodeWriter:
    def __init__(self, spec=None, *, lifecycle=None):
        self.lifecycle = lifecycle or DockerLifecycle()

    def __call__(self, state: dict[str, Any], node_config: dict[str, Any] | None = None) -> dict[str, Any]:
        task = CurrentTask(**state["current_task"])
        prompt = _build_prompt(task, node_config)
        ...
        return {**state, "worker_result": worker_result, "workspace_volume": workspace_volume}
```

**After:**
```python
class CodeWriter:
    def __init__(self, spec=None, *, lifecycle=None,
                 prompt_preamble=None, role_instructions_path=None,
                 acp_readonly_dirs=None, **kwargs):
        self.lifecycle = lifecycle or DockerLifecycle()
        self.prompt_preamble = prompt_preamble or []
        self.role_instructions_path = role_instructions_path

    def __call__(self,
                 current_task: CurrentTask,
                 workspace_volume: WorkSpace,
                 ) -> CodeWriterOutput:
        prompt = _build_prompt(current_task, self.prompt_preamble)
        ...
        return CodeWriterOutput(
            worker_result=AgentWorkerResult(...),
            workspace_volume=workspace_volume,
            commit_hash=result.commit_hash,
        )
```

**System definition node becomes:**
```json
{
  "id": "code_writer",
  "role": "code_implement_from_tests",
  "config": {
    "acp_readonly_dirs": ["/workspace/tests"],
    "role_instructions_path": "/home/claude/.claude/CLAUDE-source-code-writer.md",
    "prompt_preamble": ["Implement production code...", "Do not modify any test files."]
  },
  "inputs": ["CurrentTask", "WorkSpace"],
  "outputs": ["AgentWorkerResult", "WorkSpace", "CommitHash"]
}
```

### Commits
- **3a:** Migrate UnitTestWriter + tests
- **3b:** Migrate CodeWriter + tests
- **3c:** Migrate SoftwareReviewer + tests
- **3d:** Migrate Evaluator + tests
- **3e:** Migrate Decomposer and Dispatcher + tests
- **3f:** Update handler registry and runner
- **3g:** Update `archipelago_system.json` — replace `inputs_schema`/`outputs_schema` with `inputs`/`outputs` type lists

**Files:**
- Modify: all `src/archipelago/agents/*.py`
- Modify: `src/archipelago/handlers.py`, `src/archipelago/runner.py`
- Modify: `src/archipelago/archipelago_system.json`
- Update: all corresponding test files

---

## Phase Sequencing

```
Phase 1 (archipelago: models) ───┐
                                  ├──→ Phase 3 (archipelago: migrate agents)
Phase 2 (agent-foundry: protocol)┘
```

Phases 1 & 2 in parallel. Phase 3 requires both.

## Verification

- After each phase: `pdm run pytest` in both repos
- Phase 3: existing integration tests pass with typed agents behind connector

## Risks

| Risk | Mitigation |
|------|-----------|
| LangGraph requires dict state | Connector calls `model_dump()` at boundary |
| `{**state}` removal breaks state propagation | Verify LangGraph partial-state merge in Phase 3 tests |
| Constructor `**kwargs` hides config errors | Log unrecognized kwargs at debug level |
| `get_type_hints` doesn't resolve TypeAlias at runtime | TypeAlias resolves to the underlying type; connector handles both BaseModel and primitive types |
