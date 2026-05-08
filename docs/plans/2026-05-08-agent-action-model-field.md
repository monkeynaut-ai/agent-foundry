# Plan: AgentAction `model` field

**Branch:** `feat/declare-model`  
**Goal:** Let each `AgentAction` declare which Claude model it runs on. Different agents in the same system may use different models.

---

## Design decisions

- **Field type: `str`** — accepts both `ClaudeModel` members and raw strings for models not yet in the enum. `ClaudeModel` is a `StrEnum`, so its values satisfy a `str` annotation at runtime.
- **Required, no default** — per platform principles, choices that carry semantic weight (cost, capability, latency) must be explicit. No silent default.
- **Threading path** — `AgentAction.model` → `run_agent_in_container` reads it → passed to `_run_claude_turn` → added to the `claude` CLI command as `--model <value>`.
- **No validation against known models** — the platform passes the string straight to the CLI. Validating against a list would block new models and require an API call.

---

## Task 1 — Add `model: str` to `AgentAction`

**File:** `src/agent_foundry/primitives/models.py`

### 1a. Write failing test

In `tests/agent_foundry/primitives/test_agent_action_model.py`, add:

```python
def test_model_field_is_required(self):
    with pytest.raises(ValidationError):
        AgentAction[StubInput, StubOutput](
            name="test",
            prompt_builder=...,
            instructions_provider=...,
            executor=...,
            reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
            # model omitted — must fail
        )

def test_model_field_accepts_string(self):
    action = AgentAction[StubInput, StubOutput](
        name="test",
        model="claude-sonnet-4-6",
        ...
    )
    assert action.model == "claude-sonnet-4-6"

def test_model_field_accepts_claude_model_enum(self):
    action = AgentAction[StubInput, StubOutput](
        name="test",
        model=ClaudeModel.SONNET_4_6,
        ...
    )
    assert action.model == "claude-sonnet-4-6"
```

### 1b. Implement

Add after `reuse_policy` in `AgentAction`:

```python
model: str = Field(min_length=1)
```

Place it near `reuse_policy` (both are required, no-default fields the product must choose).

### 1c. Verify

```
pdm run pytest tests/agent_foundry/primitives/test_agent_action_model.py -x -q
```

---

## Task 2 — Thread model through `_run_claude_turn`

**Files:** `src/agent_foundry/orchestration/container_executor.py`

### 2a. Write failing test

In `tests/agent_foundry/orchestration/test_container_executor.py`, add a test asserting `--model` and the model value appear in the command passed to `exec_run`. The existing fake `RunTurn` pattern is the right seam — check the existing test structure in that file and follow it.

### 2b. Implement — `_run_claude_turn`

Add `model: str` parameter (required, keyword-only):

```python
async def _run_claude_turn(
    live: LiveContainer,
    *,
    prompt: str,
    resume_session_id: str | None,
    schema: dict[str, Any],
    model: str,
    skip_permissions: bool = False,
) -> TurnResult:
```

Inside `_do_exec`, extend cmd after `--json-schema`:

```python
cmd = [
    "gosu", "claude", "/home/claude/.local/bin/claude",
    "-p", prompt,
    "--output-format", "stream-json",
    "--verbose",
    "--json-schema", json.dumps(schema),
    "--model", model,
]
```

### 2c. Implement — `run_agent_in_container`

At the `run_turn(...)` call site (line ~453), add `model=primitive.model`:

```python
result = await run_turn(
    live,
    prompt=current_prompt,
    resume_session_id=current_resume,
    schema=schema,
    model=primitive.model,
    skip_permissions=primitive.skip_permissions,
)
```

### 2d. Verify

```
pdm run pytest tests/agent_foundry/orchestration/test_container_executor.py -x -q
```

---

## Task 3 — Update all test fixtures

Add `model=ClaudeModel.SONNET_4_6` to every `AgentAction[...]()` call across these files (use `SONNET_4_6` as the test-fixture default — it's the current primary model):

| File | Count |
|------|-------|
| `tests/agent_foundry/primitives/test_agent_action_model.py` | ~12 |
| `tests/agent_foundry/compiler/test_agent_action_compiler.py` | ~12 |
| `tests/agent_foundry/orchestration/test_container_executor.py` | check |
| `tests/agent_foundry/orchestration/test_registry.py` | 4 |
| `tests/agent_foundry/orchestration/test_file_path_verification.py` | check |
| `tests/agent_foundry/compiler/test_agent_action_spans.py` | check |
| `tests/agent_foundry/compiler/test_run_primitive_plan.py` | 1 |
| `tests/agent_foundry/primitives/test_primitive_validators.py` | 1 |
| `tests/agent_foundry/integration/test_end_to_end.py` | 1 |

Also update `lab/list_models.py` to demonstrate `ClaudeModel` usage alongside `list_claude_models()`.

### Verify

```
pdm run pytest tests/ -q -m "not integration"
```

All unit tests must be green before this plan is complete.

---

## Completion criteria

- [ ] `AgentAction` has a required `model: str` field
- [ ] `_run_claude_turn` accepts `model` and passes `--model <value>` to the CLI
- [ ] `run_agent_in_container` reads `primitive.model` and forwards it
- [ ] All unit tests pass
- [ ] `ClaudeModel.SONNET_4_6` (or any valid string) works as the `model` value in a declaration
