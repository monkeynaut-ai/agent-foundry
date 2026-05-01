# MLflow Tracing Integration Implementation Plan

> **Design:** docs/archive/mlflow-tracing-integration-design.md
> **For agents:** Use team-dev (parallel) or sdd (sequential) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MLflow tracing and run capture to Agent Foundry by emitting OpenTelemetry spans from the compiler at `AgentAction` boundaries and binding MLflow Runs to the existing `RunContext` lifecycle through an optional adapter under the `[mlflow]` extra.

**Architecture:** AF core gains a `telemetry` module (OTel-only, vendor-neutral) that defines `TelemetryConfig`, builds an OTel `TracerProvider` from it, and wraps the compiled `AgentAction` node function with span emission. A separate `mlflow_adapter` module (optional install) registers an additive attribute-translation `SpanProcessor` (`agent_foundry.*` → `mlflow.*` while preserving originals) and binds MLflow Run start/end to `RunContext` open/close lifecycle hooks introduced for this work. The class currently named `AgentRunContext` is renamed to `RunContext` because its actual scope is the entire plan execution, not just agents.

**Tech Stack:**
- `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http` (added as core dependencies)
- `mlflow >= 3.6.0` (optional, under `[mlflow]` extra)
- Pydantic v2 for all boundary types
- pytest with `asyncio_mode = "strict"`; tests run via `pdm test-all`
- Conventional commits per `jig.config.md`: `type(scope): message`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/agent_foundry/orchestration/run_context.py` | Modify | Rename `AgentRunContext` → `RunContext`; add `on_open` / `on_close` lifecycle hook fields; add `telemetry` (TelemetryConfig) and `telemetry_provider` (TracerProvider) fields so the compiler-side span helper and the MLflow adapter can find the provider per-context (no process-global state) |
| `src/agent_foundry/orchestration/runner.py` | Modify | Use `RunContext` name; invoke `on_open` after construction and `on_close` in finally (after `render_summary` so artifact specs see the rendered summary); thread `telemetry: TelemetryConfig | None` parameter; build TracerProvider per-run, store on `RunContext.telemetry_provider`, never call `trace.set_tracer_provider` (no process-global state) |
| `src/agent_foundry/orchestration/container_executor.py` | Modify | Use `RunContext` name in references and type hints |
| `src/agent_foundry/runtime/__init__.py` | Modify | Update docstring to use `RunContext` name |
| `src/agent_foundry/compiler/primitive_compiler.py` | Modify | Wrap `AgentAction` node functions with span emission via `emit_span` helper |
| `src/agent_foundry/observability/tracer.py` | Delete | Dead `ExecutionTracer`; no live call sites |
| `src/agent_foundry/observability/gates.py` | Delete | Zero live consumers (verified via grep); cleaned up alongside tracer.py |
| `src/agent_foundry/observability/__init__.py` | Delete | Module is empty after tracer.py and gates.py are removed; whole `observability/` directory goes away |
| `src/agent_foundry/orchestration/lifecycle_events.py` | Modify | Add `RUN_FAILED = "run_failed"` to `LifecycleEvent` StrEnum so failed runs have a terminal lifecycle event |
| `src/agent_foundry/orchestration/summary.py` | Modify | Treat `RUN_FAILED` as a terminal event (sets `run_ended_at`); add `failed` flag rendered in the header so `(incomplete)` only fires on truly incomplete runs |
| `tests/agent_foundry/orchestration/test_lifecycle_events.py` | Modify | Add `"RUN_FAILED"` to `EXPECTED_MEMBERS` so the sealed-set membership test passes after the enum addition |
| `tests/agent_foundry/orchestration/test_summary.py` | Modify | Add a regression test confirming `RUN_FAILED` is treated as terminal (no `(incomplete)`); add a test that the header surfaces a failed status |
| `src/agent_foundry/telemetry/__init__.py` | Create | Public exports: `TelemetryConfig`, `RunDefinition`, `RedactionPolicy`, `RunStats`, `ArtifactSpec`, `build_tracer_provider`, `emit_span` |
| `src/agent_foundry/telemetry/config.py` | Create | Pydantic models: `TelemetryConfig`, `RunDefinition`, `RedactionPolicy`, `RunStats`, `ArtifactSpec` |
| `src/agent_foundry/telemetry/attributes.py` | Create | Module-level constants for canonical attribute names (`AF_INPUT`, `AF_OUTPUT`, `AF_PRIMITIVE_TYPE`, `AF_PRIMITIVE_NAME`, `AF_RUN_ID`, plus `gen_ai.*` constants) |
| `src/agent_foundry/telemetry/setup.py` | Create | `build_tracer_provider(config) -> TracerProvider` with `BatchSpanProcessor` + `OTLPSpanExporter` |
| `src/agent_foundry/telemetry/spans.py` | Create | `emit_span(...)` context-manager; sets attributes, applies redaction, records exceptions as span errors |
| `src/agent_foundry/mlflow_adapter/__init__.py` | Create | Public `enable(config, run_context, input_model)` entry point; imports the import-guard from `extras.py` |
| `src/agent_foundry/mlflow_adapter/extras.py` | Create | Optional-dependency import guard: tries `import mlflow`, raises actionable `ImportError` if missing (per design's File Layout) |
| `src/agent_foundry/mlflow_adapter/translation.py` | Create | `MLFLOW_TRANSLATIONS` dict — table products plug into `TelemetryConfig.attribute_translations` so AF mirrors `agent_foundry.*` to `mlflow.*` at emit time (avoids OTel's "set-after-end no-op" rule) |
| `src/agent_foundry/mlflow_adapter/run_lifecycle.py` | Create | `attach_run_hooks(run_context, run_definition, redaction, input_model)` — appends MLflow `start_run`/`end_run` callables to `RunContext.on_open` / `on_close` |
| `pyproject.toml` | Modify | Add OTel core deps; add `[project.optional-dependencies] mlflow = [...]`; extend `pythonpath` to include `examples` so the live smoke test in E3 can import the demo |
| `tests/agent_foundry/orchestration/test_run_context.py` | Modify | Update imports + names to `RunContext` |
| `tests/agent_foundry/orchestration/test_run_context_hooks.py` | Create | Tests for `on_open` / `on_close` hook invocation, ordering, and exception isolation |
| `tests/agent_foundry/orchestration/test_container_executor.py` | Modify | Update imports + names to `RunContext` |
| `tests/agent_foundry/orchestration/test_file_path_verification.py` | Modify | Update imports + names to `RunContext` |
| `tests/agent_foundry/orchestration/test_runner_telemetry.py` | Create | Tests for telemetry threading through `run_primitive_plan` |
| `tests/agent_foundry/compiler/test_agent_action_compiler.py` | Modify | Update imports + names to `RunContext` |
| `tests/agent_foundry/compiler/test_run_primitive_plan.py` | Modify | Update docstring + names to `RunContext` |
| `tests/agent_foundry/compiler/test_agent_action_spans.py` | Create | Tests for span emission around `AgentAction` execution |
| `tests/agent_foundry/primitives/test_function_action_signature.py` | Modify | Update imports + names to `RunContext` |
| `tests/agent_foundry/telemetry/__init__.py` | Create | Empty test package marker |
| `tests/agent_foundry/telemetry/test_config.py` | Create | Tests for `TelemetryConfig`, `RunDefinition`, `RedactionPolicy`, `RunStats`, `ArtifactSpec` validation |
| `tests/agent_foundry/telemetry/test_attributes.py` | Create | Asserts canonical attribute-name constants exactly match the design contract |
| `tests/agent_foundry/telemetry/test_setup.py` | Create | Tests for `build_tracer_provider` |
| `tests/agent_foundry/telemetry/test_spans.py` | Create | Tests for `emit_span` using `InMemorySpanExporter` |
| `tests/agent_foundry/telemetry/test_redaction.py` | Create | Tests for `RedactionPolicy` applied to span input/output |
| `tests/agent_foundry/mlflow_adapter/__init__.py` | Create | Empty test package marker |
| `tests/agent_foundry/mlflow_adapter/test_extras.py` | Create | Tests for actionable ImportError when `mlflow` is missing |
| `tests/agent_foundry/mlflow_adapter/test_translation.py` | Create | Tests `MLFLOW_TRANSLATIONS` constant shape and that emit-time mirroring writes both `agent_foundry.*` and `mlflow.*` on the same span before `span.end()` |
| `tests/agent_foundry/mlflow_adapter/test_run_lifecycle.py` | Create | Tests using a fake `mlflow` module that `start_run`, `log_params`, `log_metrics`, `log_artifact`, `end_run` are called with the right values |
| `tests/agent_foundry/mlflow_adapter/test_enable.py` | Create | Integration test wiring telemetry + adapter end-to-end with a fake `mlflow` and `InMemorySpanExporter` |
| `tests/agent_foundry/mlflow_adapter/test_verification_demo.py` | Create | Live smoke test against a real local MLflow; gated by `AF_LIVE_MLFLOW=1` env var |
| `examples/__init__.py` | Create | Marks `examples` as a Python package so the live smoke test in E3 can `from examples.mlflow_demo.main import main` |
| `examples/mlflow_demo/__init__.py` | Create | Marks the demo as a sub-package |
| `examples/mlflow_demo/docker-compose.yaml` | Create | Local MLflow 3.6+ on `localhost:5000` with SQLite backend |
| `examples/mlflow_demo/main.py` | Create | End-to-end example product wired with a `TelemetryConfig` and `RunDefinition` |
| `examples/mlflow_demo/README.md` | Create | How to run the demo and what to look for in the MLflow UI |

---

## Phase A — Prep

### Task A1: Rename `AgentRunContext` → `RunContext`

**Files:**
- Modify: `src/agent_foundry/orchestration/run_context.py`
- Modify: `src/agent_foundry/orchestration/runner.py`
- Modify: `src/agent_foundry/orchestration/container_executor.py`
- Modify: `src/agent_foundry/compiler/primitive_compiler.py`
- Modify: `src/agent_foundry/runtime/__init__.py`
- Modify: `tests/agent_foundry/orchestration/test_run_context.py`
- Modify: `tests/agent_foundry/orchestration/test_container_executor.py`
- Modify: `tests/agent_foundry/orchestration/test_file_path_verification.py`
- Modify: `tests/agent_foundry/compiler/test_agent_action_compiler.py`
- Modify: `tests/agent_foundry/compiler/test_run_primitive_plan.py`
- Modify: `tests/agent_foundry/primitives/test_function_action_signature.py`

**Dependencies:** None.

This is a structural rename, not a behavior change. TDD red-green doesn't apply cleanly; the existing test suite is the safety net. Steps are split per file so a permission denial or merge conflict halts in a recoverable spot.

- [ ] **Step 1: Confirm baseline tests pass on current symbol.**

  Run:
  ```bash
  pdm test-all
  ```
  Expected: PASS. Establishes the baseline for the rename.

- [ ] **Step 2: Rename the class definition and module docstring.**

  In `src/agent_foundry/orchestration/run_context.py`, replace every `AgentRunContext` with `RunContext`. Module docstring update:

  ```python
  """RunContext — the per-plan-execution context carried through compiled plans.

  Constructed once at plan start (in ``run_primitive_plan``) before the compiled
  graph runs and remains active through every primitive (Sequence, Loop,
  AgentAction, FunctionAction, …). Carries plan-level state: ``run_id``,
  ``artifacts_dir``, ``lifecycle_writer``, ``cancel_event``, container
  registry, responder provider, env.

  Module-level ``current_run_context`` ContextVar + ``require_current_run_context``
  helper expose the active context to compiled nodes and to product code via
  ``agent_foundry.runtime`` accessors.
  """
  ```

  And the class:

  ```python
  class RunContext(BaseModel):
      """Per-plan-execution context threaded through compiled plan execution.

      Fields:
        - ``run_id``: unique identifier for this run (non-empty)
        - ``artifacts_dir``: directory for per-run artifacts
        - ``container_registry``: AgentContainerRegistry (duck-typed)
        - ``responder_provider``: resolves ``responder_id`` -> responder callable
        - ``lifecycle_writer``: a concrete :class:`LifecycleWriter` subclass
        - ``cancel_event``: cooperative cancellation signal. ``frozen=True`` blocks
          reassignment but callers may still mutate the event (``cancel_event.set()``).
        - ``env``: container env dict (must include CLAUDE_CODE_OAUTH_TOKEN)
      """

      model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

      run_id: str = Field(min_length=1)
      artifacts_dir: Path = Field(default_factory=_default_artifacts_dir)
      container_registry: Any
      responder_provider: Any = None
      lifecycle_writer: LifecycleWriter
      cancel_event: asyncio.Event = Field(default_factory=asyncio.Event)
      env: dict[str, str]
  ```

  Also update the `__all__` list and `require_current_run_context` error message:

  ```python
  __all__ = [
      "RunContext",
      "LifecycleWriter",
      "NoOpLifecycleWriter",
      "current_run_context",
      "require_current_run_context",
  ]


  current_run_context: ContextVar[RunContext | None] = ContextVar(
      "current_run_context", default=None
  )


  def require_current_run_context() -> RunContext:
      """Return the active ``RunContext`` or raise ``RuntimeError``."""
      ctx = current_run_context.get()
      if ctx is None:
          raise RuntimeError(
              "No active RunContext: current_run_context ContextVar is unset. "
              "A compiled node tried to access run context outside a run."
          )
      return ctx
  ```

- [ ] **Step 3: Update each call site.**

  Replace `AgentRunContext` with `RunContext` (case-sensitive, exact match) in:
  - `src/agent_foundry/orchestration/runner.py` — note: this includes the **module docstring at line 6** (`"AgentRunContext, container registry..."`) and the **`run_primitive_plan_sync` docstring at line 58** (`":class:`AgentRunContext`"`) in addition to the imports and construction site. Don't rely on the case-sensitive replacement to find these — they're prose, not code references.
  - `src/agent_foundry/orchestration/container_executor.py`
  - `src/agent_foundry/compiler/primitive_compiler.py` — note: this includes an **inline comment at line 167** (`# Resolve the current ``AgentRunContext`` once`) in addition to the imports and code references.
  - `src/agent_foundry/runtime/__init__.py` (docstring mention)
  - `tests/agent_foundry/orchestration/test_run_context.py`
  - `tests/agent_foundry/orchestration/test_container_executor.py`
  - `tests/agent_foundry/orchestration/test_file_path_verification.py`
  - `tests/agent_foundry/compiler/test_agent_action_compiler.py`
  - `tests/agent_foundry/compiler/test_run_primitive_plan.py`
  - `tests/agent_foundry/primitives/test_function_action_signature.py`

  In `tests/agent_foundry/orchestration/test_run_context.py` line 150, also update the regex matcher in `pytest.raises(RuntimeError, match="AgentRunContext")` to `pytest.raises(RuntimeError, match="RunContext")` to match the new error message.

  Also rename the test functions whose names embed the old class name, e.g. `test_agent_run_context_has_required_core_fields` → `test_run_context_has_required_core_fields`. (Function-name updates are optional for behavior but keep the test names self-explanatory.)

- [ ] **Step 4: Verify no stale references remain.**

  Run:
  ```bash
  grep -rn "AgentRunContext" src/ tests/
  ```
  Expected: no output (zero matches).

- [ ] **Step 5: Run the full test suite.**

  Run:
  ```bash
  pdm test-all
  ```
  Expected: PASS.

- [ ] **Step 6: Run the linter and type-checker.**

  Run:
  ```bash
  pdm lint
  pdm typecheck
  ```
  Expected: both PASS.

- [ ] **Step 7: Commit.**

  ```bash
  git add src/agent_foundry/orchestration/run_context.py \
          src/agent_foundry/orchestration/runner.py \
          src/agent_foundry/orchestration/container_executor.py \
          src/agent_foundry/compiler/primitive_compiler.py \
          src/agent_foundry/runtime/__init__.py \
          tests/agent_foundry/orchestration/test_run_context.py \
          tests/agent_foundry/orchestration/test_container_executor.py \
          tests/agent_foundry/orchestration/test_file_path_verification.py \
          tests/agent_foundry/compiler/test_agent_action_compiler.py \
          tests/agent_foundry/compiler/test_run_primitive_plan.py \
          tests/agent_foundry/primitives/test_function_action_signature.py
  git commit -m "refactor(runtime): rename AgentRunContext to RunContext"
  ```

---

### Task A2: Delete dead `observability/` module

**Files:**
- Delete: `src/agent_foundry/observability/tracer.py`
- Delete: `src/agent_foundry/observability/gates.py`
- Delete: `src/agent_foundry/observability/__init__.py`
- Delete: `src/agent_foundry/observability/` directory (after the above three are gone)

**Dependencies:** None.

`grep -rn "from agent_foundry.observability\|import.*agent_foundry.observability" src/ tests/` returns no matches: the entire module is dead. Removing it whole is cleaner than leaving an orphaned `gates.py` next to the new `telemetry/` module — readers shouldn't have to wonder which one is current.

- [ ] **Step 1: Confirm no live references for the entire module.**

  Run:
  ```bash
  grep -rn "from agent_foundry.observability\|import.*agent_foundry.observability\|ExecutionTracer\|FF_TRACING\|FF_TRACE_TOOL_IO\|FF_TRACE_RETRIEVAL\|FF_EVAL_GATES\|FF_DOMAIN_GATES" src/ tests/
  ```
  Expected: matches (if any) only inside `src/agent_foundry/observability/` itself.

- [ ] **Step 2: Delete the directory.**

  ```bash
  rm -rf src/agent_foundry/observability/
  ```

- [ ] **Step 3: Verify deletion didn't break tests.**

  Run:
  ```bash
  pdm test-all
  ```
  Expected: PASS.

- [ ] **Step 4: Verify lint and typecheck.**

  Run:
  ```bash
  pdm lint
  pdm typecheck
  ```
  Expected: both PASS.

- [ ] **Step 5: Commit.**

  ```bash
  git add -A src/agent_foundry/
  git commit -m "refactor(observability): remove dead observability module"
  ```

---

### Task A3: Add `on_open` / `on_close` lifecycle hooks to `RunContext` and `RUN_FAILED` lifecycle event

**Files:**
- Modify: `src/agent_foundry/orchestration/run_context.py`
- Modify: `src/agent_foundry/orchestration/runner.py`
- Modify: `src/agent_foundry/orchestration/lifecycle_events.py` (add `RUN_FAILED`)
- Modify: `src/agent_foundry/orchestration/summary.py` (treat `RUN_FAILED` as terminal)
- Modify: `tests/agent_foundry/orchestration/test_lifecycle_events.py` (add `"RUN_FAILED"` to `EXPECTED_MEMBERS`)
- Modify: `tests/agent_foundry/orchestration/test_summary.py` (regression tests for `RUN_FAILED`)
- Create: `tests/agent_foundry/orchestration/test_run_context_hooks.py`

**Dependencies:** Requires Task A1 (uses `RunContext` name).

This task does four coupled things:
1. Adds `on_open` and `on_close` callable lists to `RunContext` so the MLflow adapter (D3) can react to run lifecycle without modifying the runner's body.
2. Adds the `RUN_FAILED` lifecycle event constant and writes it on the failure path so downstream consumers see a terminal event whether the run succeeded or failed.
3. Updates existing consumers of the lifecycle stream — `summary.py`, `test_lifecycle_events.py`, `test_summary.py` — so the new event doesn't break the renderer or break a sealed-set membership test.
4. Threads the run's *final output* (or `None` on failure) through `on_close` so adapters can build metrics from the actual result rather than the input. Reorders the runner's `finally` block so `render_summary` runs *before* `on_close` hooks, allowing products' `ArtifactSpec` entries to reference the rendered summary file.

- [ ] **Step 1: Write the failing test for hook fields and invocation.**

  Create `tests/agent_foundry/orchestration/test_run_context_hooks.py`:

  ```python
  """Tests for RunContext lifecycle hooks (on_open / on_close)."""

  from __future__ import annotations

  import asyncio
  import logging
  from pathlib import Path

  import pytest
  from pydantic import BaseModel, ValidationError

  from agent_foundry.orchestration.run_context import (
      NoOpLifecycleWriter,
      RunContext,
  )


  def _ctx(tmp_path: Path, **overrides) -> RunContext:
      kwargs = dict(
          run_id="r",
          artifacts_dir=tmp_path,
          container_registry=object(),
          responder_provider=object(),
          lifecycle_writer=NoOpLifecycleWriter(),
          cancel_event=asyncio.Event(),
          env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
      )
      kwargs.update(overrides)
      return RunContext(**kwargs)


  def test_run_context_on_open_default_empty(tmp_path: Path) -> None:
      ctx = _ctx(tmp_path)
      assert ctx.on_open == []


  def test_run_context_on_close_default_empty(tmp_path: Path) -> None:
      ctx = _ctx(tmp_path)
      assert ctx.on_close == []


  def test_run_context_accepts_on_open_callables(tmp_path: Path) -> None:
      def hook(ctx: RunContext) -> None:
          pass

      rc = _ctx(tmp_path, on_open=[hook])
      assert rc.on_open == [hook]


  def test_run_context_accepts_on_close_callables(tmp_path: Path) -> None:
      def hook(ctx: RunContext, exc: BaseException | None, output: BaseModel | None) -> None:
          pass

      rc = _ctx(tmp_path, on_close=[hook])
      assert rc.on_close == [hook]


  def test_run_context_on_open_field_assignment_raises(tmp_path: Path) -> None:
      """frozen=True blocks field reassignment but list.append works.

      Documents the mutation pattern: `ctx.on_open.append(hook)` is the supported way
      to add a hook after construction; `ctx.on_open = [hook]` raises ValidationError.
      """
      ctx = _ctx(tmp_path)
      with pytest.raises(ValidationError):
          ctx.on_open = [lambda c: None]


  def test_run_context_on_open_append_after_construction(tmp_path: Path) -> None:
      ctx = _ctx(tmp_path)
      ctx.on_open.append(lambda c: None)
      assert len(ctx.on_open) == 1
  ```

- [ ] **Step 2: Run the test, verify it fails.**

  Run:
  ```bash
  pdm test-unit -k test_run_context_on_open_default_empty
  ```
  Expected: FAIL with `AttributeError: 'RunContext' object has no attribute 'on_open'` or a Pydantic `ValidationError` rejecting the `on_open` kwarg.

- [ ] **Step 3: Add the hook fields to `RunContext`.**

  Edit `src/agent_foundry/orchestration/run_context.py`. Add to the imports:

  ```python
  from collections.abc import Callable
  ```

  Add the fields to the class (preserving existing fields and `frozen=True`):

  ```python
  class RunContext(BaseModel):
      # ... existing fields ...

      on_open: list[Callable[["RunContext"], None]] = Field(default_factory=list)
      """Callables invoked once the RunContext is constructed and the
      ``current_run_context`` ContextVar is set, before the compiled graph runs.
      Each hook receives the context. Hook exceptions are caught, logged, and
      do not block other hooks or the run itself.

      Mutation contract: append to this list (``ctx.on_open.append(hook)``); do
      NOT reassign the field (``ctx.on_open = [...]`` raises ValidationError
      because RunContext has ``frozen=True``).

      Iteration semantics: the runner iterates this list with a live reference
      (``for hook in ctx.on_open``), not a snapshot. This means a hook may
      append additional hooks during execution and they will run in the same
      pass. The MLflow adapter relies on this to register lifecycle hooks from
      within an on_open hook. Do not change this iteration to a snapshot
      (``for hook in list(ctx.on_open)``) without auditing all callers.
      """

      on_close: list[Callable[["RunContext", BaseException | None, BaseModel | None], None]] = Field(
          default_factory=list
      )
      """Callables invoked when the run is exiting, before teardown. Receives:
        - the context
        - the exception (or None on success)
        - the run's final output BaseModel (or None on failure / before output materialises)

      Hook exceptions are caught, logged, and do not block other hooks or
      teardown.

      Same mutation contract and iteration semantics as ``on_open``.
      """
  ```

- [ ] **Step 4: Run the test, verify it passes.**

  Run:
  ```bash
  pdm test-unit -k "test_run_context_on_open_default_empty or test_run_context_on_close_default_empty or test_run_context_accepts_on_open_callables or test_run_context_accepts_on_close_callables"
  ```
  Expected: 4 PASSED.

- [ ] **Step 5: Write the failing test for runner-side invocation.**

  Append to `tests/agent_foundry/orchestration/test_run_context_hooks.py`:

  ```python
  # -- Runner-side hook invocation --


  class _Empty(BaseModel):
      pass


  @pytest.mark.asyncio
  async def test_run_primitive_plan_invokes_on_open_in_order(tmp_path: Path) -> None:
      from agent_foundry.orchestration.runner import run_primitive_plan
      from agent_foundry.primitives.models import FunctionAction
      from agent_foundry.primitives.plan import PrimitivePlan

      observed: list[str] = []
      hooks = [
          lambda ctx: observed.append(f"open-1:{ctx.run_id}"),
          lambda ctx: observed.append(f"open-2:{ctx.run_id}"),
      ]

      def fn(_: _Empty) -> _Empty:
          return _Empty()

      action = FunctionAction[_Empty, _Empty](function=fn)
      plan = PrimitivePlan(root=action)

      await run_primitive_plan(
          plan,
          initial_state=_Empty(),
          artifacts_dir=tmp_path,
          workspace_volume="vol",
          base_image_tag="img",
          responder_provider=lambda _id: lambda *a, **k: None,
          run_id="run-hooks",
          on_open=hooks,
      )

      assert observed == ["open-1:run-hooks", "open-2:run-hooks"]


  @pytest.mark.asyncio
  async def test_run_primitive_plan_invokes_on_close_with_none_exc_and_output_on_success(
      tmp_path: Path,
  ) -> None:
      from agent_foundry.orchestration.runner import run_primitive_plan
      from agent_foundry.primitives.models import FunctionAction
      from agent_foundry.primitives.plan import PrimitivePlan

      observed: list[tuple[BaseException | None, BaseModel | None]] = []

      def fn(_: _Empty) -> _Empty:
          return _Empty()

      action = FunctionAction[_Empty, _Empty](function=fn)
      plan = PrimitivePlan(root=action)

      await run_primitive_plan(
          plan,
          initial_state=_Empty(),
          artifacts_dir=tmp_path,
          workspace_volume="vol",
          base_image_tag="img",
          responder_provider=lambda _id: lambda *a, **k: None,
          run_id="run-success",
          on_close=[lambda _ctx, exc, output: observed.append((exc, output))],
      )

      assert len(observed) == 1
      exc, output = observed[0]
      assert exc is None
      assert isinstance(output, _Empty)


  @pytest.mark.asyncio
  async def test_run_primitive_plan_invokes_on_close_with_exception_and_none_output_on_failure(
      tmp_path: Path,
  ) -> None:
      from agent_foundry.orchestration.runner import run_primitive_plan
      from agent_foundry.primitives.models import FunctionAction
      from agent_foundry.primitives.plan import PrimitivePlan

      observed: list[tuple[BaseException | None, BaseModel | None]] = []

      def boom(_: _Empty) -> _Empty:
          raise RuntimeError("boom")

      action = FunctionAction[_Empty, _Empty](function=boom)
      plan = PrimitivePlan(root=action)

      with pytest.raises(RuntimeError, match="boom"):
          await run_primitive_plan(
              plan,
              initial_state=_Empty(),
              artifacts_dir=tmp_path,
              workspace_volume="vol",
              base_image_tag="img",
              responder_provider=lambda _id: lambda *a, **k: None,
              run_id="run-fail",
              on_close=[lambda _ctx, exc, output: observed.append((exc, output))],
          )

      assert len(observed) == 1
      exc, output = observed[0]
      assert isinstance(exc, RuntimeError)
      assert "boom" in str(exc)
      assert output is None


  @pytest.mark.asyncio
  async def test_run_primitive_plan_writes_run_failed_lifecycle_event(
      tmp_path: Path,
  ) -> None:
      """The lifecycle JSONL must end with RUN_FAILED on the failure path
      so downstream consumers can distinguish 'died mid-run' from 'in progress'."""
      import json

      from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
      from agent_foundry.orchestration.runner import run_primitive_plan
      from agent_foundry.primitives.models import FunctionAction
      from agent_foundry.primitives.plan import PrimitivePlan

      def boom(_: _Empty) -> _Empty:
          raise RuntimeError("boom")

      action = FunctionAction[_Empty, _Empty](function=boom)
      plan = PrimitivePlan(root=action)

      with pytest.raises(RuntimeError, match="boom"):
          await run_primitive_plan(
              plan,
              initial_state=_Empty(),
              artifacts_dir=tmp_path,
              workspace_volume="vol",
              base_image_tag="img",
              responder_provider=lambda _id: lambda *a, **k: None,
              run_id="run-fail-lc",
          )

      lifecycle_path = next(tmp_path.rglob("lifecycle.jsonl"))
      events = [json.loads(line) for line in lifecycle_path.read_text().splitlines()]
      types = [e["type"] for e in events]
      # Use membership rather than position so a future on_close hook that
      # emits a domain event doesn't break the test. The contract is "exactly
      # one terminal event, and it's RUN_FAILED" — not "RUN_FAILED is last".
      # Use ``.value`` for parity with the existing test_run_primitive_plan tests.
      assert LifecycleEvent.RUN_STARTED.value in types
      assert LifecycleEvent.RUN_FAILED.value in types
      assert LifecycleEvent.RUN_ENDED.value not in types


  @pytest.mark.asyncio
  async def test_run_primitive_plan_writes_run_ended_lifecycle_event_on_success(
      tmp_path: Path,
  ) -> None:
      import json

      from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
      from agent_foundry.orchestration.runner import run_primitive_plan
      from agent_foundry.primitives.models import FunctionAction
      from agent_foundry.primitives.plan import PrimitivePlan

      def fn(_: _Empty) -> _Empty:
          return _Empty()

      action = FunctionAction[_Empty, _Empty](function=fn)
      plan = PrimitivePlan(root=action)

      await run_primitive_plan(
          plan,
          initial_state=_Empty(),
          artifacts_dir=tmp_path,
          workspace_volume="vol",
          base_image_tag="img",
          responder_provider=lambda _id: lambda *a, **k: None,
          run_id="run-ok-lc",
      )

      lifecycle_path = next(tmp_path.rglob("lifecycle.jsonl"))
      events = [json.loads(line) for line in lifecycle_path.read_text().splitlines()]
      types = [e["type"] for e in events]
      assert LifecycleEvent.RUN_STARTED.value in types
      assert LifecycleEvent.RUN_ENDED.value in types
      assert LifecycleEvent.RUN_FAILED.value not in types


  @pytest.mark.asyncio
  async def test_run_primitive_plan_isolates_hook_exceptions(
      tmp_path: Path, caplog: pytest.LogCaptureFixture
  ) -> None:
      from agent_foundry.orchestration.runner import run_primitive_plan
      from agent_foundry.primitives.models import FunctionAction
      from agent_foundry.primitives.plan import PrimitivePlan

      observed: list[str] = []

      def fn(_: _Empty) -> _Empty:
          return _Empty()

      action = FunctionAction[_Empty, _Empty](function=fn)
      plan = PrimitivePlan(root=action)

      def bad(_ctx) -> None:
          raise ValueError("hook-1 failed")

      def good(_ctx) -> None:
          observed.append("hook-2 ran")

      with caplog.at_level(logging.ERROR):
          await run_primitive_plan(
              plan,
              initial_state=_Empty(),
              artifacts_dir=tmp_path,
              workspace_volume="vol",
              base_image_tag="img",
              responder_provider=lambda _id: lambda *a, **k: None,
              run_id="run-iso",
              on_open=[bad, good],
          )

      assert observed == ["hook-2 ran"]
      assert any("hook-1 failed" in record.message for record in caplog.records)
  ```

- [ ] **Step 6: Run the failing tests.**

  Run:
  ```bash
  pdm test-unit -k test_run_primitive_plan_invokes_on_open_in_order
  ```
  Expected: FAIL with `TypeError: run_primitive_plan() got an unexpected keyword argument 'on_open'`.

- [ ] **Step 7: Add `RUN_FAILED` to the lifecycle events enum.**

  Edit `src/agent_foundry/orchestration/lifecycle_events.py`:

  ```python
  class LifecycleEvent(StrEnum):
      """Stable wire constants for the lifecycle.jsonl event stream."""

      RUN_STARTED = "run_started"
      RUN_ENDED = "run_ended"
      RUN_FAILED = "run_failed"  # NEW — terminal event on the failure path
      AGENT_CONTAINER_STARTED = "agent_container_started"
      # ... rest unchanged
  ```

- [ ] **Step 8: Update consumers of the lifecycle event stream.**

  Adding `RUN_FAILED` ripples into two existing files:

  **(a)** `tests/agent_foundry/orchestration/test_lifecycle_events.py` has a sealed-set membership test (`test_lifecycle_event_member_set_is_exact`) comparing the actual `LifecycleEvent` members against an `EXPECTED_MEMBERS` set. Add `"RUN_FAILED"`:

  ```python
  EXPECTED_MEMBERS = {
      "RUN_STARTED",
      "RUN_ENDED",
      "RUN_FAILED",  # NEW
      "AGENT_CONTAINER_STARTED",
      # ... rest unchanged
  }
  ```

  **(b)** `src/agent_foundry/orchestration/summary.py` reads the lifecycle JSONL and branches on `LifecycleEvent.RUN_ENDED.value` to populate `run_ended_at`. Without an update, every failed run renders as `(incomplete)` in the header even though the run actually terminated. Update the relevant branch:

  ```python
  for event in events:
      event_type = event.get("type")
      if event_type == LifecycleEvent.RUN_STARTED.value:
          run_started_at = event.get("ts")
      elif event_type == LifecycleEvent.RUN_ENDED.value:
          run_ended_at = event.get("ts")
      elif event_type == LifecycleEvent.RUN_FAILED.value:  # NEW
          run_ended_at = event.get("ts")
          run_failed = True
  ```

  Where `run_failed` is a new local boolean (default `False`) the renderer reads to choose between `"completed"` and `"failed"` in the header. Keep the `(incomplete)` marker reserved for runs with no terminal event at all.

  **(c)** `tests/agent_foundry/orchestration/test_summary.py` — add regression tests:

  ```python
  def test_summary_treats_run_failed_as_terminal(tmp_path: Path) -> None:
      """RUN_FAILED is a terminal event; (incomplete) must not appear."""
      # Build a lifecycle.jsonl with RUN_STARTED then RUN_FAILED.
      # Render summary; assert run_ended_at is set and (incomplete) is absent.
      # The header surfaces a "failed" status.
      ...


  def test_summary_marks_run_failed_in_header(tmp_path: Path) -> None:
      """The summary header must clearly indicate a failed terminal state."""
      ...
  ```

  (Use the existing test fixtures and helpers in `test_summary.py` as the template — match the file's idiom rather than the sketch above.)

- [ ] **Step 9: Implement runner-side hook invocation, RUN_FAILED writing, output threading, and finally-block reordering.**

  Edit `src/agent_foundry/orchestration/runner.py`. Add the parameters to `run_primitive_plan`, invoke the hooks, write the right terminal lifecycle event, pass the final output to `on_close`, and **reorder the `finally` block so existing teardown (specifically `render_summary`) runs before `on_close` hooks**. The reorder lets a product `ArtifactSpec(path=run_dir/"summary.txt")` reference the rendered summary file when the MLflow adapter logs artifacts. Insert a private helper for safe iteration:

  ```python
  from collections.abc import Callable

  ...


  def _safe_invoke_hooks(
      hooks: list[Callable[..., None]],
      *args,
      label: str,
  ) -> None:
      """Invoke each hook; isolate exceptions, log them, continue.

      Iterates the live list (not a snapshot) so a hook may register additional
      hooks during execution and have them run in the same pass. The MLflow
      adapter relies on this: an on_open hook calls ``enable()`` which appends
      MLflow lifecycle hooks to the same on_open/on_close lists.

      Catches BaseException to isolate one hook's failure from another. Note
      this means a CancelledError raised by a hook body itself (distinct from
      a CancelledError passed as the ``exc`` argument to on_close hooks) will
      be swallowed. Hooks must be synchronous and must not re-raise
      BaseException subclasses that should propagate to the runner. If async
      hooks are added later, this helper must be re-evaluated.
      """
      for hook in hooks:
          try:
              hook(*args)
          except BaseException:  # noqa: BLE001 -- isolate hooks so one failure doesn't break others
              logger.exception("RunContext %s hook raised; continuing", label)


  async def run_primitive_plan(
      plan: PrimitivePlan,
      *,
      initial_state: BaseModel,
      artifacts_dir: Path,
      workspace_volume: str,
      base_image_tag: str,
      responder_provider: ResponderProvider,
      run_id: str | None = None,
      on_open: list[Callable[["RunContext"], None]] | None = None,
      on_close: list[Callable[["RunContext", BaseException | None, BaseModel | None], None]] | None = None,
  ) -> BaseModel:
      """... (existing docstring) ..."""
      ...
      run_ctx = RunContext(
          run_id=resolved_run_id,
          artifacts_dir=run_dir,
          container_registry=registry,
          responder_provider=responder_provider,
          lifecycle_writer=lifecycle,
          cancel_event=cancel,
          env={"CLAUDE_CODE_OAUTH_TOKEN": oauth_token} if oauth_token else {},
          on_open=list(on_open or []),
          on_close=list(on_close or []),
      )

      ...
      token = current_run_context.set(run_ctx)
      lifecycle.append(LifecycleEvent.RUN_STARTED, run_id=resolved_run_id)
      _safe_invoke_hooks(run_ctx.on_open, run_ctx, label="on_open")

      caught_exc: BaseException | None = None
      final_output: BaseModel | None = None
      try:
          graph = _compile_primitive(plan)
          result_dict = await graph.ainvoke(initial_state.model_dump())
          final_output = root_out.model_validate(result_dict)
          # ... existing success-path bookkeeping (note: do NOT write RUN_ENDED
          # here — it's written below in finally, exactly once, with the
          # right success/failure value) ...
      except BaseException as exc:
          caught_exc = exc
          raise
      finally:
          # Order matters:
          #   1. Write the terminal lifecycle event so the JSONL stream has a
          #      terminal record before downstream consumers (render_summary,
          #      hooks) read it.
          terminal = (
              LifecycleEvent.RUN_FAILED if caught_exc is not None else LifecycleEvent.RUN_ENDED
          )
          lifecycle.append(terminal, run_id=resolved_run_id)
          #
          #   2. Existing teardown that produces files in artifacts_dir
          #      (registry.shutdown_all, render_summary). Each remains in its
          #      own try/except so a teardown failure can't prevent on_close
          #      from firing.
          # ... existing teardown (registry.shutdown_all, render_summary) ...
          #
          #   3. on_close hooks fire AFTER render_summary. This lets a product's
          #      RunDefinition.artifacts include ArtifactSpec entries that
          #      reference summary.txt, summary.html, or anything else
          #      render_summary writes.
          _safe_invoke_hooks(
              run_ctx.on_close, run_ctx, caught_exc, final_output, label="on_close"
          )
          #
          #   4. ContextVar reset, signal handler removal, lifecycle.close
          #      remain at the end as they currently are.
  ```

  Important: the existing `lifecycle.append(LifecycleEvent.RUN_ENDED, ...)` call in the success path of the current implementation must be **removed** so that exactly one terminal event is written in `finally`. Verify by inspecting `runner.py` after editing — there should be no `RUN_ENDED` write in the `try` block.

  Also import `RunContext` in the type annotation if needed.

- [ ] **Step 10: Run the new and updated tests.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/orchestration/test_run_context_hooks.py \
                tests/agent_foundry/orchestration/test_lifecycle_events.py \
                tests/agent_foundry/orchestration/test_summary.py
  ```
  Expected: PASS — including the new RUN_FAILED-related tests in `test_run_context_hooks.py` and the regression coverage in `test_summary.py`.

- [ ] **Step 11: Run the full test suite to confirm nothing else broke.**

  Run:
  ```bash
  pdm test-all
  ```
  Expected: PASS.

- [ ] **Step 12: Lint and typecheck.**

  Run:
  ```bash
  pdm lint
  pdm typecheck
  ```
  Expected: both PASS.

- [ ] **Step 13: Commit.**

  ```bash
  git add src/agent_foundry/orchestration/run_context.py \
          src/agent_foundry/orchestration/runner.py \
          src/agent_foundry/orchestration/lifecycle_events.py \
          src/agent_foundry/orchestration/summary.py \
          tests/agent_foundry/orchestration/test_run_context_hooks.py \
          tests/agent_foundry/orchestration/test_lifecycle_events.py \
          tests/agent_foundry/orchestration/test_summary.py
  git commit -m "feat(runtime): add lifecycle hooks and RUN_FAILED terminal event"
  ```

---

### Task A4: Add OpenTelemetry and MLflow dependencies

**Files:**
- Modify: `pyproject.toml`

**Dependencies:** None (independent of A1-A3).

- [ ] **Step 1: Add OTel core dependencies via PDM.**

  Run:
  ```bash
  pdm add opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
  ```
  Expected: PDM installs the packages and updates `pyproject.toml` and `pdm.lock`.

- [ ] **Step 2: Add MLflow as an optional extra.**

  Edit `pyproject.toml` to add the `[project.optional-dependencies]` block (or extend it if present):

  ```toml
  [project.optional-dependencies]
  mlflow = ["mlflow>=3.6.0"]
  ```

- [ ] **Step 3: Verify the MLflow extra resolves.**

  Run:
  ```bash
  pdm install -G mlflow
  ```
  Expected: `mlflow` and its transitive deps installed without resolver errors.

- [ ] **Step 4: Verify nothing else broke.**

  Run:
  ```bash
  pdm test-all
  ```
  Expected: PASS.

- [ ] **Step 5: Commit.**

  ```bash
  git add pyproject.toml pdm.lock
  git commit -m "chore(deps): add opentelemetry core and optional mlflow"
  ```

---

## Phase B — Telemetry module (AF core)

### Task B1: Define `TelemetryConfig` and supporting models

**Files:**
- Create: `src/agent_foundry/telemetry/__init__.py`
- Create: `src/agent_foundry/telemetry/config.py`
- Create: `tests/agent_foundry/telemetry/__init__.py`
- Create: `tests/agent_foundry/telemetry/test_config.py`

**Dependencies:** Requires Task A4.

- [ ] **Step 1: Write the failing test.**

  Create `tests/agent_foundry/telemetry/__init__.py` (empty file).

  Create `tests/agent_foundry/telemetry/test_config.py`:

  ```python
  """Tests for the telemetry config Pydantic models."""

  from __future__ import annotations

  from pathlib import Path

  import pytest
  from pydantic import BaseModel, ValidationError

  from agent_foundry.telemetry.config import (
      ArtifactSpec,
      RedactionPolicy,
      RunDefinition,
      RunStats,
      TelemetryConfig,
  )


  class _Input(BaseModel):
      ticket_id: str
      kind: str = "bug"


  class _Output(BaseModel):
      success: bool


  # -- TelemetryConfig --


  def test_telemetry_config_minimum_fields() -> None:
      config = TelemetryConfig(
          otlp_endpoint="http://localhost:5000/v1/traces",
          otlp_headers={},
          service_name="archipelago",
      )
      assert config.otlp_endpoint == "http://localhost:5000/v1/traces"
      assert config.otlp_headers == {}
      assert config.service_name == "archipelago"
      assert config.redaction is None
      assert config.run_definition is None


  def test_telemetry_config_requires_endpoint() -> None:
      with pytest.raises(ValidationError):
          TelemetryConfig(  # type: ignore[call-arg]
              otlp_headers={},
              service_name="archipelago",
          )


  def test_telemetry_config_requires_service_name() -> None:
      with pytest.raises(ValidationError):
          TelemetryConfig(  # type: ignore[call-arg]
              otlp_endpoint="http://localhost:5000/v1/traces",
              otlp_headers={},
          )


  # -- RunDefinition --


  def test_run_definition_evaluates_callables() -> None:
      rd = RunDefinition(
          name=lambda inp: f"ticket-{inp.ticket_id}",
          params=lambda inp: {"ticket_id": inp.ticket_id, "kind": inp.kind},
          tags={"product": "archipelago"},
          metrics=lambda out, stats: {"success": float(out.success), "duration_ms": stats.duration_ms},
      )
      sample = _Input(ticket_id="42", kind="feature")
      assert rd.name(sample) == "ticket-42"
      assert rd.params(sample) == {"ticket_id": "42", "kind": "feature"}


  def test_run_definition_metrics_callable_consumes_output_and_stats() -> None:
      from agent_foundry.telemetry.config import RunStats

      rd = RunDefinition(
          name=lambda _: "n",
          params=lambda _: {},
          tags={},
          metrics=lambda out, stats: {"success": float(out.success)},
      )
      out = _Output(success=True)
      stats = RunStats()
      assert rd.metrics(out, stats) == {"success": 1.0}


  def test_run_definition_tags_can_be_callable() -> None:
      rd = RunDefinition(
          name=lambda _: "n",
          params=lambda _: {},
          tags=lambda inp: {"kind": inp.kind},
          metrics=lambda _out, _s: {},
      )
      sample = _Input(ticket_id="1", kind="bug")
      assert callable(rd.tags)
      assert rd.tags(sample) == {"kind": "bug"}


  def test_run_definition_artifacts_default_empty() -> None:
      rd = RunDefinition(
          name=lambda _: "n",
          params=lambda _: {},
          tags={},
          metrics=lambda _out, _stats: {},
      )
      assert rd.artifacts == []


  # -- ArtifactSpec --


  def test_artifact_spec_path_required(tmp_path: Path) -> None:
      spec = ArtifactSpec(path=tmp_path / "result.json")
      assert spec.path == tmp_path / "result.json"
      assert spec.artifact_path is None


  def test_artifact_spec_optional_artifact_path(tmp_path: Path) -> None:
      spec = ArtifactSpec(path=tmp_path / "x.json", artifact_path="folder/x.json")
      assert spec.artifact_path == "folder/x.json"


  # -- RedactionPolicy --


  def test_redaction_policy_defaults_to_none() -> None:
      policy = RedactionPolicy()
      assert policy.redact_input is None
      assert policy.redact_output is None


  def test_redaction_policy_accepts_callables() -> None:
      def red_in(m: _Input) -> _Input:
          return _Input(ticket_id="REDACTED", kind=m.kind)

      policy = RedactionPolicy(redact_input=red_in)
      assert policy.redact_input is red_in
      assert policy.redact_output is None


  # -- RunStats --


  def test_run_stats_zero_defaults() -> None:
      stats = RunStats()
      assert stats.duration_ms == 0.0
      assert stats.span_count == 0
      assert stats.error_count == 0
      assert stats.total_input_tokens == 0
      assert stats.total_output_tokens == 0


  def test_run_stats_explicit_values() -> None:
      stats = RunStats(
          duration_ms=123.4,
          span_count=5,
          error_count=1,
          total_input_tokens=100,
          total_output_tokens=200,
      )
      assert stats.duration_ms == 123.4
      assert stats.span_count == 5
      assert stats.error_count == 1
      assert stats.total_input_tokens == 100
      assert stats.total_output_tokens == 200
  ```

- [ ] **Step 2: Run the test to verify it fails.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/telemetry/test_config.py
  ```
  Expected: FAIL with `ModuleNotFoundError: No module named 'agent_foundry.telemetry.config'`.

- [ ] **Step 3: Create the package and config models.**

  Create `src/agent_foundry/telemetry/__init__.py`:

  ```python
  """Telemetry — OpenTelemetry emission, vendor-neutral.

  AF emits OTel spans at primitive boundaries. The ``mlflow_adapter`` (under
  the optional ``[mlflow]`` extra) is a separate module that consumes these
  spans; the telemetry module never imports MLflow.
  """

  from agent_foundry.telemetry.config import (
      ArtifactSpec,
      RedactionPolicy,
      RunDefinition,
      RunStats,
      TelemetryConfig,
  )

  __all__ = [
      "ArtifactSpec",
      "RedactionPolicy",
      "RunDefinition",
      "RunStats",
      "TelemetryConfig",
  ]
  ```

  Create `src/agent_foundry/telemetry/config.py`:

  ```python
  """Pydantic models defining the telemetry surface that products configure."""

  from __future__ import annotations

  from collections.abc import Callable
  from pathlib import Path
  from typing import Any

  from pydantic import BaseModel, ConfigDict, Field


  class RunStats(BaseModel):
      """Run-level statistics computed at run close, passed to RunDefinition.metrics.

      Field availability for the foundational scope of MLflow tracing integration:

      - ``duration_ms``: live (computed from monotonic clock at run open/close).
      - ``span_count``, ``error_count``, ``total_input_tokens``, ``total_output_tokens``:
        ALL ZERO. These fields will be populated by a follow-up task that
        accumulates per-span stats during the run. Until that lands, products
        should not branch on these fields (e.g. don't write
        ``metrics=lambda out, s: {"err_rate": s.error_count / s.span_count}`` —
        it will divide by zero).

      The fields are kept in the model now so the metrics callable signature is
      stable across the follow-up: products can declare them today, get zeros
      for now, and start receiving real values once span tracking lands.
      """

      model_config = ConfigDict(frozen=True)

      duration_ms: float = 0.0
      span_count: int = 0
      error_count: int = 0
      total_input_tokens: int = 0
      total_output_tokens: int = 0


  class ArtifactSpec(BaseModel):
      """Declares a file to log to the active MLflow run as an artifact."""

      model_config = ConfigDict(arbitrary_types_allowed=True)

      path: Path
      """Absolute path on disk. Typically points under ``RunContext.artifacts_dir``."""

      artifact_path: str | None = None
      """Optional sub-path within the run's artifact store. Defaults to None
      (logged at the artifact root)."""


  class RedactionPolicy(BaseModel):
      """Per-primitive redaction callables applied before serialisation to spans."""

      model_config = ConfigDict(arbitrary_types_allowed=True)

      redact_input: Callable[[BaseModel], BaseModel] | None = None
      """If set, applied to the input model before it becomes ``agent_foundry.input``.
      Must return the same model type. Receives a copy."""

      redact_output: Callable[[BaseModel], BaseModel] | None = None
      """If set, applied to the output model before it becomes ``agent_foundry.output``.
      Must return the same model type. Receives a copy."""


  class RunDefinition(BaseModel):
      """Product-declared shape of one MLflow run.

      ``name``, ``params``, and ``tags`` callables receive the plan's *input*
      model and produce the corresponding MLflow concept at run open.

      ``metrics`` is different — it receives the plan's *final output* model
      (or the input model on the failure path before output materialises; see
      ``on_close`` semantics below) and a ``RunStats`` summary, and returns the
      metrics to log at run close. The runner passes the actual output through
      ``RunContext.on_close`` to make this work.

      On the failure path, the output is None — products that read fields off
      the output must defensively handle that (return ``{}``, return only
      stats-derived metrics, etc.).
      """

      model_config = ConfigDict(arbitrary_types_allowed=True)

      name: Callable[[BaseModel], str]
      """Receives the plan's input model. Returns the MLflow run name."""

      params: Callable[[BaseModel], dict[str, Any]]
      """Receives the plan's input model. Returns params to log at run open
      (logged via ``mlflow.log_params``). Apply ``RedactionPolicy.redact_input``
      before reading sensitive fields."""

      tags: dict[str, str] | Callable[[BaseModel], dict[str, str]]
      """Static dict or callable receiving the plan's input model. Tags
      attached to the run at open time."""

      metrics: Callable[[BaseModel | None, RunStats], dict[str, float]]
      """Receives the plan's final OUTPUT model (or None on the failure path)
      and a ``RunStats`` summary. Returns metrics to log at run close. Read
      output fields defensively — handle ``out is None`` for failed runs."""

      artifacts: list[ArtifactSpec] = Field(default_factory=list)
      """Files to log to the run as artifacts at run close."""


  class TelemetryConfig(BaseModel):
      """Product opt-in to telemetry emission. Construct in app startup, pass to
      ``run_primitive_plan(..., telemetry=config)``. Absence (``None``) disables
      emission entirely.
      """

      model_config = ConfigDict(arbitrary_types_allowed=True)

      otlp_endpoint: str = Field(min_length=1)
      """OTLP/HTTP endpoint URL, e.g. ``http://localhost:5000/v1/traces`` for
      a local MLflow."""

      otlp_headers: dict[str, str]
      """Headers to attach to OTLP requests, e.g. ``{"x-mlflow-experiment-id": "1"}``."""

      service_name: str = Field(min_length=1)
      """OTel resource ``service.name`` attribute. Identifies the AF product."""

      attribute_translations: dict[str, str] = Field(default_factory=dict)
      """Per-attribute mirror table applied at emit time. When AF sets a
      source attribute (e.g. ``agent_foundry.input``), it also sets the
      translated attribute (e.g. ``mlflow.spanInputs``) with the same value
      atomically — both are written before ``span.end()``, so neither is
      lost to OTel's "set after end is a no-op" rule.

      AF core stays vendor-neutral — this is just a data table. Adapters
      provide suitable defaults; for the MLflow adapter, products typically
      pass ``MLFLOW_TRANSLATIONS`` from ``agent_foundry.mlflow_adapter``.
      """

      redaction: RedactionPolicy | None = None
      run_definition: RunDefinition | None = None
  ```

- [ ] **Step 4: Run the tests, verify they pass.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/telemetry/test_config.py
  ```
  Expected: 12 PASSED.

- [ ] **Step 5: Lint and typecheck.**

  Run:
  ```bash
  pdm lint
  pdm typecheck
  ```
  Expected: both PASS.

- [ ] **Step 6: Commit.**

  ```bash
  git add src/agent_foundry/telemetry/__init__.py \
          src/agent_foundry/telemetry/config.py \
          tests/agent_foundry/telemetry/__init__.py \
          tests/agent_foundry/telemetry/test_config.py
  git commit -m "feat(telemetry): add TelemetryConfig and run-shape models"
  ```

---

### Task B2: Canonical attribute name constants

**Files:**
- Create: `src/agent_foundry/telemetry/attributes.py`
- Create: `tests/agent_foundry/telemetry/test_attributes.py`
- Modify: `src/agent_foundry/telemetry/__init__.py`

**Dependencies:** Requires Task B1.

- [ ] **Step 1: Write the failing test.**

  Create `tests/agent_foundry/telemetry/test_attributes.py`:

  ```python
  """The attribute namespace contract from the design doc.

  These tests pin the exact string values. Changes here are breaking
  changes — downstream consumers depend on them.
  """

  from __future__ import annotations

  from agent_foundry.telemetry import attributes


  def test_af_input_constant() -> None:
      assert attributes.AF_INPUT == "agent_foundry.input"


  def test_af_output_constant() -> None:
      assert attributes.AF_OUTPUT == "agent_foundry.output"


  def test_af_primitive_type_constant() -> None:
      assert attributes.AF_PRIMITIVE_TYPE == "agent_foundry.primitive_type"


  def test_af_primitive_name_constant() -> None:
      assert attributes.AF_PRIMITIVE_NAME == "agent_foundry.primitive_name"


  def test_af_run_id_constant() -> None:
      assert attributes.AF_RUN_ID == "agent_foundry.run_id"


  def test_gen_ai_operation_name_constant() -> None:
      assert attributes.GEN_AI_OPERATION_NAME == "gen_ai.operation.name"


  def test_gen_ai_request_model_constant() -> None:
      assert attributes.GEN_AI_REQUEST_MODEL == "gen_ai.request.model"


  def test_gen_ai_usage_input_tokens_constant() -> None:
      assert attributes.GEN_AI_USAGE_INPUT_TOKENS == "gen_ai.usage.input_tokens"


  def test_gen_ai_usage_output_tokens_constant() -> None:
      assert attributes.GEN_AI_USAGE_OUTPUT_TOKENS == "gen_ai.usage.output_tokens"
  ```

- [ ] **Step 2: Run the test to verify it fails.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/telemetry/test_attributes.py
  ```
  Expected: FAIL with `ModuleNotFoundError: No module named 'agent_foundry.telemetry.attributes'`.

- [ ] **Step 3: Create the constants module.**

  Create `src/agent_foundry/telemetry/attributes.py`:

  ```python
  """Canonical attribute names for AF telemetry spans.

  These are the names AF emits on every span. Two namespaces:

  - ``agent_foundry.*`` — AF-internal concepts that no external standard
    covers cleanly. The MLflow adapter translates these additively to
    ``mlflow.*`` without removing originals.
  - ``gen_ai.*`` — OpenTelemetry GenAI semantic conventions, used as-is.
    Recognised natively by MLflow's OTLP translator (renders typed spans
    without remapping) and by other OTel-compatible backends.

  This module is the contract surface. Changes to constants are breaking
  changes — downstream consumers (translators, dashboards, queries) depend
  on them.
  """

  AF_INPUT = "agent_foundry.input"
  """JSON-serialised input model (post-redaction)."""

  AF_OUTPUT = "agent_foundry.output"
  """JSON-serialised output model (post-redaction)."""

  AF_PRIMITIVE_TYPE = "agent_foundry.primitive_type"
  """The Python class name of the primitive emitting this span,
  e.g. ``"AgentAction"``."""

  AF_PRIMITIVE_NAME = "agent_foundry.primitive_name"
  """The primitive's diagnostic ``name`` field if set; otherwise absent."""

  AF_RUN_ID = "agent_foundry.run_id"
  """The active ``RunContext.run_id`` for cross-referencing spans to runs."""

  GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
  """OTel GenAI operation name, e.g. ``"chat"`` for an LLM chat completion."""

  GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
  """OTel GenAI model identifier reported by the executor."""

  GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
  """OTel GenAI input-token usage if reported."""

  GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
  """OTel GenAI output-token usage if reported."""
  ```

  Update `src/agent_foundry/telemetry/__init__.py` to expose the module:

  ```python
  """Telemetry — OpenTelemetry emission, vendor-neutral."""

  from agent_foundry.telemetry import attributes
  from agent_foundry.telemetry.config import (
      ArtifactSpec,
      RedactionPolicy,
      RunDefinition,
      RunStats,
      TelemetryConfig,
  )

  __all__ = [
      "ArtifactSpec",
      "RedactionPolicy",
      "RunDefinition",
      "RunStats",
      "TelemetryConfig",
      "attributes",
  ]
  ```

- [ ] **Step 4: Run the tests, verify they pass.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/telemetry/test_attributes.py
  ```
  Expected: 9 PASSED.

- [ ] **Step 5: Lint and typecheck.**

  Run:
  ```bash
  pdm lint
  pdm typecheck
  ```
  Expected: both PASS.

- [ ] **Step 6: Commit.**

  ```bash
  git add src/agent_foundry/telemetry/__init__.py \
          src/agent_foundry/telemetry/attributes.py \
          tests/agent_foundry/telemetry/test_attributes.py
  git commit -m "feat(telemetry): add canonical span-attribute constants"
  ```

---

### Task B3: Build OTel `TracerProvider` from `TelemetryConfig`

**Files:**
- Create: `src/agent_foundry/telemetry/setup.py`
- Create: `tests/agent_foundry/telemetry/test_setup.py`
- Modify: `src/agent_foundry/telemetry/__init__.py`

**Dependencies:** Requires Task B1.

- [ ] **Step 1: Write the failing test.**

  Create `tests/agent_foundry/telemetry/test_setup.py`:

  ```python
  """Tests for build_tracer_provider."""

  from __future__ import annotations

  import pytest
  from opentelemetry.sdk.resources import Resource
  from opentelemetry.sdk.trace import TracerProvider

  from agent_foundry.telemetry.config import TelemetryConfig
  from agent_foundry.telemetry.setup import build_tracer_provider


  def _config(**overrides) -> TelemetryConfig:
      kwargs = dict(
          otlp_endpoint="http://localhost:5000/v1/traces",
          otlp_headers={"x-mlflow-experiment-id": "1"},
          service_name="archipelago",
      )
      kwargs.update(overrides)
      return TelemetryConfig(**kwargs)


  def test_build_tracer_provider_returns_TracerProvider() -> None:
      provider = build_tracer_provider(_config())
      assert isinstance(provider, TracerProvider)
      provider.shutdown()


  def test_build_tracer_provider_sets_service_name_resource() -> None:
      provider = build_tracer_provider(_config(service_name="archipelago"))
      assert provider.resource.attributes.get("service.name") == "archipelago"
      provider.shutdown()


  def test_build_tracer_provider_emits_to_configured_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
      """Behavioural test that the provider's exporter pipeline targets the configured endpoint.

      Avoids reaching into ``provider._active_span_processor._span_processors`` because that's
      OTel SDK internals that can rename across versions. Instead, monkeypatch the OTLP
      exporter constructor and assert it was constructed with the right endpoint and headers.
      """
      observed: dict[str, object] = {}

      from agent_foundry.telemetry import setup as setup_mod

      original = setup_mod.OTLPSpanExporter

      def capturing_exporter(*, endpoint: str, headers: dict[str, str]):
          observed["endpoint"] = endpoint
          observed["headers"] = headers
          return original(endpoint=endpoint, headers=headers)

      monkeypatch.setattr(setup_mod, "OTLPSpanExporter", capturing_exporter)
      provider = build_tracer_provider(
          _config(otlp_endpoint="http://example:5000/v1/traces", otlp_headers={"k": "v"})
      )
      assert observed["endpoint"] == "http://example:5000/v1/traces"
      assert observed["headers"] == {"k": "v"}
      provider.shutdown()
  ```

- [ ] **Step 2: Run the failing test.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/telemetry/test_setup.py
  ```
  Expected: FAIL with `ModuleNotFoundError: No module named 'agent_foundry.telemetry.setup'`.

- [ ] **Step 3: Implement `build_tracer_provider`.**

  Create `src/agent_foundry/telemetry/setup.py`:

  ```python
  """Construct an OpenTelemetry TracerProvider from a TelemetryConfig."""

  from __future__ import annotations

  from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
  from opentelemetry.sdk.resources import Resource
  from opentelemetry.sdk.trace import TracerProvider
  from opentelemetry.sdk.trace.export import BatchSpanProcessor

  from agent_foundry.telemetry.config import TelemetryConfig


  def build_tracer_provider(config: TelemetryConfig) -> TracerProvider:
      """Build a TracerProvider with a BatchSpanProcessor exporting to the
      configured OTLP/HTTP endpoint. Caller is responsible for installing the
      provider on the OTel SDK and calling ``shutdown()`` for clean flush.
      """
      resource = Resource.create({"service.name": config.service_name})
      provider = TracerProvider(resource=resource)
      exporter = OTLPSpanExporter(
          endpoint=config.otlp_endpoint,
          headers=config.otlp_headers,
      )
      provider.add_span_processor(BatchSpanProcessor(exporter))
      return provider
  ```

  Update `src/agent_foundry/telemetry/__init__.py` to expose it:

  ```python
  from agent_foundry.telemetry.setup import build_tracer_provider

  __all__ = [
      ...,  # existing
      "build_tracer_provider",
  ]
  ```

- [ ] **Step 4: Run the tests.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/telemetry/test_setup.py
  ```
  Expected: 3 PASSED.

- [ ] **Step 5: Lint and typecheck.**

  Run:
  ```bash
  pdm lint
  pdm typecheck
  ```
  Expected: both PASS.

- [ ] **Step 6: Commit.**

  ```bash
  git add src/agent_foundry/telemetry/setup.py \
          src/agent_foundry/telemetry/__init__.py \
          tests/agent_foundry/telemetry/test_setup.py
  git commit -m "feat(telemetry): build OTel TracerProvider from TelemetryConfig"
  ```

---

### Task B4: `emit_span` helper

**Files:**
- Create: `src/agent_foundry/telemetry/spans.py`
- Create: `tests/agent_foundry/telemetry/test_spans.py`
- Modify: `src/agent_foundry/telemetry/__init__.py`

**Dependencies:** Requires Tasks B1, B2.

- [ ] **Step 1: Write the failing test.**

  Create `tests/agent_foundry/telemetry/test_spans.py`:

  ```python
  """Tests for emit_span using OTel's InMemorySpanExporter.

  Tests construct a RunContext with a TracerProvider anchored on it and set
  the ``current_run_context`` ContextVar — emit_span resolves the provider from
  the context, so no process-global state is touched.
  """

  from __future__ import annotations

  import asyncio
  from pathlib import Path

  import pytest
  from opentelemetry.sdk.trace import TracerProvider
  from opentelemetry.sdk.trace.export import SimpleSpanProcessor
  from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
  from opentelemetry.trace.status import StatusCode
  from pydantic import BaseModel

  from agent_foundry.orchestration.run_context import (
      NoOpLifecycleWriter,
      RunContext,
      current_run_context,
  )
  from agent_foundry.telemetry import attributes
  from agent_foundry.telemetry.spans import emit_span


  class _In(BaseModel):
      ticket_id: str


  class _Out(BaseModel):
      success: bool


  @pytest.fixture()
  def in_memory_exporter(tmp_path: Path):
      """Build a TracerProvider with an InMemorySpanExporter, anchor it on a
      RunContext, and set the ContextVar. emit_span resolves the provider from
      the context — nothing is set on the OTel global tracer-provider state.
      """
      exporter = InMemorySpanExporter()
      provider = TracerProvider()
      provider.add_span_processor(SimpleSpanProcessor(exporter))
      ctx = RunContext(
          run_id="test-spans",
          artifacts_dir=tmp_path,
          container_registry=object(),
          responder_provider=object(),
          lifecycle_writer=NoOpLifecycleWriter(),
          cancel_event=asyncio.Event(),
          env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
          telemetry_provider=provider,
      )
      token = current_run_context.set(ctx)
      try:
          yield exporter
      finally:
          current_run_context.reset(token)
          provider.shutdown()


  def test_emit_span_emits_one_span_with_input_and_output(in_memory_exporter) -> None:
      in_memory_exporter.clear()
      with emit_span(
          name="agent_foundry.AgentAction",
          primitive_type="AgentAction",
          primitive_name="reviewer",
          input_model=_In(ticket_id="42"),
          run_id="run-1",
          redaction=None,
      ) as handle:
          handle.set_output(_Out(success=True))

      spans = in_memory_exporter.get_finished_spans()
      assert len(spans) == 1
      span = spans[0]
      assert span.name == "agent_foundry.AgentAction"
      assert span.attributes[attributes.AF_PRIMITIVE_TYPE] == "AgentAction"
      assert span.attributes[attributes.AF_PRIMITIVE_NAME] == "reviewer"
      assert span.attributes[attributes.AF_RUN_ID] == "run-1"
      assert "ticket_id" in span.attributes[attributes.AF_INPUT]
      assert "success" in span.attributes[attributes.AF_OUTPUT]
      assert span.status.status_code == StatusCode.OK


  def test_emit_span_records_exception_and_sets_error_status(in_memory_exporter) -> None:
      in_memory_exporter.clear()
      with pytest.raises(RuntimeError, match="boom"):
          with emit_span(
              name="agent_foundry.AgentAction",
              primitive_type="AgentAction",
              primitive_name=None,
              input_model=_In(ticket_id="42"),
              run_id=None,
              redaction=None,
          ):
              raise RuntimeError("boom")

      spans = in_memory_exporter.get_finished_spans()
      assert len(spans) == 1
      span = spans[0]
      assert span.status.status_code == StatusCode.ERROR
      assert any(event.name == "exception" for event in span.events)


  def test_emit_span_omits_run_id_attribute_when_none(in_memory_exporter) -> None:
      in_memory_exporter.clear()
      with emit_span(
          name="agent_foundry.AgentAction",
          primitive_type="AgentAction",
          primitive_name=None,
          input_model=_In(ticket_id="42"),
          run_id=None,
          redaction=None,
      ) as handle:
          handle.set_output(_Out(success=True))

      span = in_memory_exporter.get_finished_spans()[0]
      assert attributes.AF_RUN_ID not in span.attributes


  def test_emit_span_set_token_usage_writes_gen_ai_attributes(in_memory_exporter) -> None:
      in_memory_exporter.clear()
      with emit_span(
          name="agent_foundry.AgentAction",
          primitive_type="AgentAction",
          primitive_name=None,
          input_model=_In(ticket_id="42"),
          run_id=None,
          redaction=None,
      ) as handle:
          handle.set_output(_Out(success=True))
          handle.set_model_id("claude-opus-4-7")
          handle.set_token_usage(input_tokens=120, output_tokens=85)

      span = in_memory_exporter.get_finished_spans()[0]
      assert span.attributes[attributes.GEN_AI_REQUEST_MODEL] == "claude-opus-4-7"
      assert span.attributes[attributes.GEN_AI_USAGE_INPUT_TOKENS] == 120
      assert span.attributes[attributes.GEN_AI_USAGE_OUTPUT_TOKENS] == 85


  def test_emit_span_is_noop_when_no_run_context_active() -> None:
      """No active RunContext → no provider → emit_span yields a no-op handle.

      The body still runs and exceptions still propagate, but no span emerges
      and the handle's setters are no-ops. This is the path for callers who
      run without telemetry configured (telemetry=None on run_primitive_plan).
      """
      # Note: no fixture — current_run_context is unset for this test.
      with emit_span(
          name="x",
          primitive_type="X",
          primitive_name=None,
          input_model=_In(ticket_id="1"),
          run_id=None,
          redaction=None,
      ) as handle:
          # Setters must not raise even though no span exists.
          handle.set_output(_Out(success=True))
          handle.set_model_id("claude")
          handle.set_token_usage(input_tokens=1, output_tokens=1)


  def test_emit_span_is_noop_when_run_context_has_no_provider(tmp_path: Path) -> None:
      """RunContext active but telemetry_provider is None → no-op."""
      ctx = RunContext(
          run_id="no-prov",
          artifacts_dir=tmp_path,
          container_registry=object(),
          responder_provider=object(),
          lifecycle_writer=NoOpLifecycleWriter(),
          cancel_event=asyncio.Event(),
          env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
          telemetry_provider=None,
      )
      token = current_run_context.set(ctx)
      try:
          with emit_span(
              name="x",
              primitive_type="X",
              primitive_name=None,
              input_model=_In(ticket_id="1"),
              run_id=None,
              redaction=None,
          ) as handle:
              handle.set_output(_Out(success=True))
      finally:
          current_run_context.reset(token)


  def test_emit_span_noop_propagates_exception_when_no_provider() -> None:
      """No active provider must not silently swallow exceptions raised in
      the body. Telemetry is independent of error propagation."""
      with pytest.raises(RuntimeError, match="boom"):
          with emit_span(
              name="x",
              primitive_type="X",
              primitive_name=None,
              input_model=_In(ticket_id="1"),
              run_id=None,
              redaction=None,
          ):
              raise RuntimeError("boom")
  ```

- [ ] **Step 2: Run the failing test.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/telemetry/test_spans.py
  ```
  Expected: FAIL with `ModuleNotFoundError: No module named 'agent_foundry.telemetry.spans'`.

- [ ] **Step 3: Implement `emit_span`.**

  Create `src/agent_foundry/telemetry/spans.py`:

  ```python
  """Span emission helper used by the compiler at primitive boundaries."""

  from __future__ import annotations

  from collections.abc import Iterator
  from contextlib import contextmanager
  from dataclasses import dataclass

  from opentelemetry import trace
  from opentelemetry.trace import Status, StatusCode
  from pydantic import BaseModel

  from agent_foundry.telemetry import attributes
  from agent_foundry.telemetry.config import RedactionPolicy


  @dataclass
  class SpanHandle:
      """In-band handle returned by ``emit_span`` for setting output and
      LLM-specific attributes mid-execution.
      """

      _span: trace.Span | None  # None when telemetry is off — handle is a no-op
      _redaction: RedactionPolicy | None
      _translations: dict[str, str]  # source-attr → mirror-attr table

      def _set(self, key: str, value: object) -> None:
          """Set ``key`` on the span and mirror to any translated key.

          Mirroring happens before ``span.end()``, so both attributes land on
          the live span — they cannot be lost to OTel's "set-after-end is a
          no-op" rule.
          """
          if self._span is None:
              return
          self._span.set_attribute(key, value)
          mirror = self._translations.get(key)
          if mirror is not None:
              self._span.set_attribute(mirror, value)

      def set_output(self, model: BaseModel) -> None:
          if self._span is None:
              return
          if self._redaction is not None and self._redaction.redact_output is not None:
              model = self._redaction.redact_output(model)
              if not isinstance(model, BaseModel):
                  raise TypeError(
                      "RedactionPolicy.redact_output must return a Pydantic BaseModel; "
                      f"got {type(model).__name__}"
                  )
          self._set(attributes.AF_OUTPUT, model.model_dump_json())

      def set_model_id(self, model_id: str) -> None:
          self._set(attributes.GEN_AI_REQUEST_MODEL, model_id)

      def set_token_usage(self, *, input_tokens: int, output_tokens: int) -> None:
          self._set(attributes.GEN_AI_USAGE_INPUT_TOKENS, input_tokens)
          self._set(attributes.GEN_AI_USAGE_OUTPUT_TOKENS, output_tokens)

      def set_operation_name(self, name: str) -> None:
          """Set the OTel GenAI operation name (e.g. ``"chat"`` for an LLM call).

          Uses the handle's direct span reference rather than
          ``trace.get_current_span()`` so the attribute lands correctly even
          when the caller is on a worker thread (LangGraph dispatches sync
          executors via ``asyncio.to_thread``, and OTel's current-span
          ContextVar may not propagate into that thread).
          """
          self._set(attributes.GEN_AI_OPERATION_NAME, name)


  def _resolve_provider_and_translations() -> tuple[trace.TracerProvider | None, dict[str, str]]:
      """Return the active RunContext's TracerProvider and translation table.

      Per-run isolation: provider stored on ``RunContext.telemetry_provider``;
      translation table from ``RunContext.telemetry.attribute_translations``.
      No global state involved.
      """
      from agent_foundry.orchestration.run_context import current_run_context

      ctx = current_run_context.get()
      if ctx is None:
          return None, {}
      provider = ctx.telemetry_provider
      translations = (
          ctx.telemetry.attribute_translations
          if ctx.telemetry is not None
          else {}
      )
      return provider, translations


  @contextmanager
  def emit_span(
      *,
      name: str,
      primitive_type: str,
      primitive_name: str | None,
      input_model: BaseModel,
      run_id: str | None,
      redaction: RedactionPolicy | None,
  ) -> Iterator[SpanHandle]:
      """Emit one OTel span for a primitive's execution.

      Sets ``agent_foundry.*`` attributes on entry. Exceptions in the body are
      recorded on the span and re-raised. The yielded handle exposes
      ``set_output``, ``set_model_id``, and ``set_token_usage`` so the caller
      can fill in attributes that are only known after execution.

      If no telemetry provider is set on the active ``RunContext`` (telemetry
      is off, or no RunContext is active), yields a no-op ``SpanHandle`` and
      does not call into the OTel SDK at all. The body still runs and exceptions
      still propagate normally — the only effect is that no span is emitted.
      """
      provider, translations = _resolve_provider_and_translations()
      if provider is None:
          yield SpanHandle(_span=None, _redaction=redaction, _translations={})
          return

      def _set_with_mirror(span: trace.Span, key: str, value: object) -> None:
          span.set_attribute(key, value)
          mirror = translations.get(key)
          if mirror is not None:
              span.set_attribute(mirror, value)

      tracer = provider.get_tracer("agent_foundry")
      with tracer.start_as_current_span(name) as span:
          _set_with_mirror(span, attributes.AF_PRIMITIVE_TYPE, primitive_type)
          if primitive_name is not None:
              _set_with_mirror(span, attributes.AF_PRIMITIVE_NAME, primitive_name)
          if run_id is not None:
              _set_with_mirror(span, attributes.AF_RUN_ID, run_id)

          if redaction is not None and redaction.redact_input is not None:
              redacted_input = redaction.redact_input(input_model)
              if not isinstance(redacted_input, BaseModel):
                  raise TypeError(
                      "RedactionPolicy.redact_input must return a Pydantic BaseModel; "
                      f"got {type(redacted_input).__name__}"
                  )
              _set_with_mirror(span, attributes.AF_INPUT, redacted_input.model_dump_json())
          else:
              _set_with_mirror(span, attributes.AF_INPUT, input_model.model_dump_json())

          handle = SpanHandle(_span=span, _redaction=redaction, _translations=translations)
          try:
              yield handle
          except BaseException as exc:
              span.record_exception(exc)
              span.set_status(Status(StatusCode.ERROR, str(exc)))
              raise
          else:
              span.set_status(Status(StatusCode.OK))
  ```

  Update `src/agent_foundry/telemetry/__init__.py`:

  ```python
  from agent_foundry.telemetry.spans import SpanHandle, emit_span

  __all__ = [
      ...,  # existing
      "SpanHandle",
      "emit_span",
  ]
  ```

- [ ] **Step 4: Run the tests.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/telemetry/test_spans.py
  ```
  Expected: 4 PASSED.

- [ ] **Step 5: Lint and typecheck.**

  Run:
  ```bash
  pdm lint
  pdm typecheck
  ```
  Expected: both PASS.

- [ ] **Step 6: Commit.**

  ```bash
  git add src/agent_foundry/telemetry/spans.py \
          src/agent_foundry/telemetry/__init__.py \
          tests/agent_foundry/telemetry/test_spans.py
  git commit -m "feat(telemetry): add primitive-boundary span emission helper"
  ```

---

### Task B5: Wire span emission into `_compile_agent_action`

**Files:**
- Modify: `src/agent_foundry/compiler/primitive_compiler.py`
- Create: `tests/agent_foundry/compiler/test_agent_action_spans.py`

**Dependencies:** Requires Tasks A1, B4.

- [ ] **Step 1: Write the failing test.**

  Create `tests/agent_foundry/compiler/test_agent_action_spans.py`:

  ```python
  """Tests for OTel span emission around AgentAction execution.

  Per-test isolation: each test builds its own TracerProvider, anchors it on
  a RunContext, and sets the ``current_run_context`` ContextVar. emit_span
  resolves the provider from the context — no global state is touched.
  """

  from __future__ import annotations

  import asyncio
  from pathlib import Path

  import pytest
  from opentelemetry.sdk.trace import TracerProvider
  from opentelemetry.sdk.trace.export import SimpleSpanProcessor
  from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
  from opentelemetry.trace.status import StatusCode
  from pydantic import BaseModel

  from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy
  from agent_foundry.primitives.plan import PrimitivePlan
  from agent_foundry.telemetry import attributes


  class _In(BaseModel):
      ticket_id: str


  class _Out(BaseModel):
      success: bool


  @pytest.fixture()
  def exporter_and_provider() -> tuple[InMemorySpanExporter, TracerProvider]:
      exp = InMemorySpanExporter()
      provider = TracerProvider()
      provider.add_span_processor(SimpleSpanProcessor(exp))
      yield exp, provider
      provider.shutdown()


  def _build_action(executor) -> AgentAction[_In, _Out]:
      return AgentAction[_In, _Out](
          name="reviewer",
          prompt_builder=lambda inp: f"prompt:{inp.ticket_id}",
          instructions_provider=lambda _: "instructions",
          executor=executor,
          reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
      )


  def test_agent_action_emits_one_span_per_invocation(
      exporter_and_provider, tmp_path: Path
  ) -> None:
      from agent_foundry.compiler.primitive_compiler import _compile_primitive
      from agent_foundry.orchestration.run_context import (
          NoOpLifecycleWriter,
          RunContext,
          current_run_context,
      )

      exporter, provider = exporter_and_provider

      def fake_executor(*, primitive, prompt, instructions, run_ctx) -> _Out:
          return _Out(success=True)

      action = _build_action(fake_executor)
      plan = PrimitivePlan(root=action)

      ctx = RunContext(
          run_id="run-spans",
          artifacts_dir=tmp_path,
          container_registry=object(),
          responder_provider=object(),
          lifecycle_writer=NoOpLifecycleWriter(),
          cancel_event=asyncio.Event(),
          env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
          telemetry_provider=provider,  # anchor provider on the run context
      )
      tok = current_run_context.set(ctx)
      try:
          graph = _compile_primitive(plan)
          graph.invoke(_In(ticket_id="42").model_dump())
      finally:
          current_run_context.reset(tok)

      spans = exporter.get_finished_spans()
      assert len(spans) == 1
      span = spans[0]
      assert span.attributes[attributes.AF_PRIMITIVE_TYPE] == "AgentAction"
      assert span.attributes[attributes.AF_PRIMITIVE_NAME] == "reviewer"
      assert span.attributes[attributes.AF_RUN_ID] == "run-spans"
      assert span.attributes["gen_ai.operation.name"] == "chat"
      assert "ticket_id" in span.attributes[attributes.AF_INPUT]
      assert "success" in span.attributes[attributes.AF_OUTPUT]
      assert span.status.status_code == StatusCode.OK


  def test_agent_action_executor_exception_records_error_span(
      exporter_and_provider, tmp_path: Path
  ) -> None:
      from agent_foundry.compiler.primitive_compiler import _compile_primitive
      from agent_foundry.orchestration.run_context import (
          NoOpLifecycleWriter,
          RunContext,
          current_run_context,
      )

      exporter, provider = exporter_and_provider

      def boom_executor(*, primitive, prompt, instructions, run_ctx) -> _Out:
          raise RuntimeError("executor blew up")

      action = _build_action(boom_executor)
      plan = PrimitivePlan(root=action)

      ctx = RunContext(
          run_id="run-fail",
          artifacts_dir=tmp_path,
          container_registry=object(),
          responder_provider=object(),
          lifecycle_writer=NoOpLifecycleWriter(),
          cancel_event=asyncio.Event(),
          env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
          telemetry_provider=provider,
      )
      tok = current_run_context.set(ctx)
      try:
          graph = _compile_primitive(plan)
          with pytest.raises(RuntimeError, match="executor blew up"):
              graph.invoke(_In(ticket_id="42").model_dump())
      finally:
          current_run_context.reset(tok)

      spans = exporter.get_finished_spans()
      assert len(spans) == 1
      assert spans[0].status.status_code == StatusCode.ERROR
  ```

- [ ] **Step 2: Run the failing test.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/compiler/test_agent_action_spans.py
  ```
  Expected: FAIL — no span is emitted, `len(spans) == 0` assertion fails.

- [ ] **Step 3: Refactor `_validate_and_return` and `_prepare` to surface the typed models.**

  Edit `src/agent_foundry/compiler/primitive_compiler.py`. Two coupled refactors:

  **(a)** The current `_validate_and_return` helper at lines 519–526 does both validation and `model_dump()` in one shot, preventing the caller from passing the typed model to `emit_span`'s `set_output(...)`. Split the responsibilities — return the model:

  ```python
  def _validate_typed(result: Any) -> BaseModel:
      """Validate the executor's return type. Returns the typed model unchanged."""
      if not isinstance(result, output_type):
          raise PrimitiveCompilationError(
              f"AgentAction {node_id}: executor returned "
              f"{type(result).__name__}, expected {output_type.__name__}",
              primitive_type=node_id,
          )
      return result

  # _validate_and_return is removed. Callers do `_validate_typed(result).model_dump()`
  # explicitly when they need the dict for LangGraph state, and pass the typed model
  # to span instrumentation in between.
  ```

  **(b)** The current `_prepare` at lines 528–541 calls `input_type.model_validate(state)` internally but discards the result. The node functions need that model for `emit_span(input_model=...)`. Update `_prepare` to return it as a 5th element instead of re-validating in the body:

  ```python
  def _prepare(state: dict[str, Any]) -> tuple[Any, str, str, Any, BaseModel]:
      _validate_boundary(state, input_type, node_id)
      model_input = input_type.model_validate(state)
      prompt = prompt_builder(model_input)
      instructions = instructions_provider(model_input)

      from agent_foundry.orchestration.run_context import (
          require_current_run_context,
      )

      run_ctx = require_current_run_context()
      return action, prompt, instructions, run_ctx, model_input
  ```

- [ ] **Step 4: Wire span emission into `_compile_agent_action`.**

  In the same file, replace the `node_fn_async` and `node_fn_sync` definitions to wrap the executor call with `emit_span`. The full structure (preserving every existing behavior — the executor still receives all four kwargs, `_prepare` is sync, output is dumped before returning to LangGraph):

  ```python
  from agent_foundry.telemetry import attributes
  from agent_foundry.telemetry.spans import emit_span

  ...


  if executor_is_async:

      async def node_fn_async(state: dict[str, Any]) -> dict[str, Any]:
          # _prepare returns the validated input model alongside the rest so we
          # don't double-validate. Update _prepare's return type to include
          # model_input as a 5th element.
          primitive, prompt, instructions, run_ctx, model_input = _prepare(state)
          redaction = (
              run_ctx.telemetry.redaction
              if getattr(run_ctx, "telemetry", None) is not None
              else None
          )

          with emit_span(
              name=f"agent_foundry.AgentAction.{action.name}",
              primitive_type="AgentAction",
              primitive_name=action.name,
              input_model=model_input,
              run_id=run_ctx.run_id,
              redaction=redaction,
          ) as handle:
              # Use the handle's direct span reference, not
              # ``trace.get_current_span()`` — the latter reads OTel's
              # current-span ContextVar, which may not propagate into worker
              # threads when sync executors run via ``asyncio.to_thread``.
              handle.set_operation_name("chat")
              result = await executor(
                  primitive=primitive,
                  prompt=prompt,
                  instructions=instructions,
                  run_ctx=run_ctx,
              )
              typed = _validate_typed(result)
              handle.set_output(typed)
              return typed.model_dump()

      graph.add_node(
          node_id, RunnableCallable(None, node_fn_async, name=node_id, trace=False)
      )
  else:

      def node_fn_sync(state: dict[str, Any]) -> dict[str, Any]:
          primitive, prompt, instructions, run_ctx, model_input = _prepare(state)
          redaction = (
              run_ctx.telemetry.redaction
              if getattr(run_ctx, "telemetry", None) is not None
              else None
          )

          with emit_span(
              name=f"agent_foundry.AgentAction.{action.name}",
              primitive_type="AgentAction",
              primitive_name=action.name,
              input_model=model_input,
              run_id=run_ctx.run_id,
              redaction=redaction,
          ) as handle:
              # Use the handle's direct span reference, not
              # ``trace.get_current_span()`` — the latter reads OTel's
              # current-span ContextVar, which may not propagate into worker
              # threads when sync executors run via ``asyncio.to_thread``.
              handle.set_operation_name("chat")
              result = executor(
                  primitive=primitive,
                  prompt=prompt,
                  instructions=instructions,
                  run_ctx=run_ctx,
              )
              typed = _validate_typed(result)
              handle.set_output(typed)
              return typed.model_dump()

      graph.add_node(node_id, node_fn_sync)
  ```

  Notes on the corrections vs an earlier draft of this plan:
  - The executor is called with all four kwargs (`primitive`, `prompt`, `instructions`, `run_ctx`) — matching every existing executor's contract (`run_agent_in_container`, all test stubs).
  - `_prepare` is **synchronous**; do NOT `await` it. The async-vs-sync executor branching is what makes the outer node `async def` or `def`, not anything inside `_prepare`.
  - `_validate_typed` returns the typed `BaseModel` instance so it can be passed to `handle.set_output(typed)`. Its `.model_dump()` is called separately for the LangGraph return value.
  - `redaction` is read from `run_ctx.telemetry.redaction` via `getattr` — the `telemetry` field is added in B6, so this code degrades to `None` when B5 lands first (before B6 is implemented) and lights up automatically when B6 adds the field. No follow-up edit needed here.

- [ ] **Step 5: Run the new tests.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/compiler/test_agent_action_spans.py
  ```
  Expected: 2 PASSED.

- [ ] **Step 6: Run the existing AgentAction compiler tests to confirm no regression.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/compiler/test_agent_action_compiler.py
  ```
  Expected: PASS (existing behavior preserved — every executor stub still receives all four kwargs).

- [ ] **Step 7: Run the full test suite.**

  Run:
  ```bash
  pdm test-all
  ```
  Expected: PASS.

- [ ] **Step 8: Lint and typecheck.**

  Run:
  ```bash
  pdm lint
  pdm typecheck
  ```
  Expected: both PASS.

- [ ] **Step 9: Commit.**

  ```bash
  git add src/agent_foundry/compiler/primitive_compiler.py \
          tests/agent_foundry/compiler/test_agent_action_spans.py
  git commit -m "feat(compiler): emit OTel span around AgentAction execution"
  ```

---

### Task B6: Thread `TelemetryConfig` through `run_primitive_plan`

**Files:**
- Modify: `src/agent_foundry/orchestration/runner.py`
- Modify: `src/agent_foundry/orchestration/run_context.py` (add stash field for `TelemetryConfig`)
- Modify: `src/agent_foundry/compiler/primitive_compiler.py` (read redaction from the stashed config)
- Create: `tests/agent_foundry/orchestration/test_runner_telemetry.py`

**Dependencies:** Requires Tasks A3, B3, B5.

- [ ] **Step 1: Write the failing test.**

  Create `tests/agent_foundry/orchestration/test_runner_telemetry.py`:

  ```python
  """Tests for telemetry threading through run_primitive_plan.

  Per-run isolation: the runner builds a TracerProvider, anchors it on the
  RunContext (via the new ``telemetry_provider`` field), and never calls
  ``trace.set_tracer_provider`` (which would be process-global). Tests verify
  the provider is set on the context, used during the run, and shut down
  afterward — without any process-global state.
  """

  from __future__ import annotations

  from pathlib import Path

  import pytest
  from pydantic import BaseModel

  from agent_foundry.orchestration.runner import run_primitive_plan
  from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy
  from agent_foundry.primitives.plan import PrimitivePlan
  from agent_foundry.telemetry import TelemetryConfig


  class _In(BaseModel):
      ticket_id: str = "1"


  class _Out(BaseModel):
      success: bool = True


  def _action() -> AgentAction[_In, _Out]:
      def executor(*, primitive, prompt, instructions, run_ctx):
          return _Out(success=True)

      return AgentAction[_In, _Out](
          name="reviewer",
          prompt_builder=lambda _: "p",
          instructions_provider=lambda _: "i",
          executor=executor,
          reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
      )


  @pytest.mark.asyncio
  async def test_run_primitive_plan_with_no_telemetry_leaves_run_context_provider_unset(
      tmp_path: Path,
  ) -> None:
      """telemetry=None → RunContext.telemetry_provider is None during execution.

      Use an on_open hook to capture the active RunContext's provider value.
      """
      observed: dict[str, object] = {}
      plan = PrimitivePlan(root=_action())

      def capture(ctx) -> None:
          observed["provider"] = ctx.telemetry_provider

      await run_primitive_plan(
          plan,
          initial_state=_In(),
          artifacts_dir=tmp_path,
          workspace_volume="vol",
          base_image_tag="img",
          responder_provider=lambda _id: lambda *a, **k: None,
          run_id="r-no-tel",
          telemetry=None,
          on_open=[capture],
      )

      assert observed["provider"] is None


  @pytest.mark.asyncio
  async def test_run_primitive_plan_with_telemetry_anchors_provider_on_run_context(
      tmp_path: Path,
  ) -> None:
      """When telemetry=config is passed, the runner builds a TracerProvider and
      stores it on RunContext.telemetry_provider. No global mutation of
      OTel's tracer-provider state.
      """
      from opentelemetry.sdk.trace import TracerProvider

      observed: dict[str, object] = {}

      config = TelemetryConfig(
          otlp_endpoint="http://localhost:5000/v1/traces",
          otlp_headers={"x-mlflow-experiment-id": "1"},
          service_name="archipelago-test",
      )
      plan = PrimitivePlan(root=_action())

      def capture(ctx) -> None:
          observed["provider"] = ctx.telemetry_provider

      await run_primitive_plan(
          plan,
          initial_state=_In(),
          artifacts_dir=tmp_path,
          workspace_volume="vol",
          base_image_tag="img",
          responder_provider=lambda _id: lambda *a, **k: None,
          run_id="r-with-tel",
          telemetry=config,
          on_open=[capture],
      )

      assert isinstance(observed["provider"], TracerProvider)
      # The provider's resource carries the configured service name
      assert observed["provider"].resource.attributes.get("service.name") == "archipelago-test"


  @pytest.mark.asyncio
  async def test_run_primitive_plan_telemetry_provider_shut_down_on_success(
      tmp_path: Path, monkeypatch
  ) -> None:
      shutdowns: list[bool] = []
      from agent_foundry.telemetry import setup as setup_mod

      original_build = setup_mod.build_tracer_provider

      def tracking_build(cfg):
          provider = original_build(cfg)
          original_shutdown = provider.shutdown

          def tracking_shutdown(*a, **k):
              shutdowns.append(True)
              return original_shutdown(*a, **k)

          provider.shutdown = tracking_shutdown  # type: ignore[method-assign]
          return provider

      monkeypatch.setattr(setup_mod, "build_tracer_provider", tracking_build)

      config = TelemetryConfig(
          otlp_endpoint="http://localhost:5000/v1/traces",
          otlp_headers={},
          service_name="archipelago-test",
      )
      plan = PrimitivePlan(root=_action())

      await run_primitive_plan(
          plan,
          initial_state=_In(),
          artifacts_dir=tmp_path,
          workspace_volume="vol",
          base_image_tag="img",
          responder_provider=lambda _id: lambda *a, **k: None,
          run_id="r-shutdown",
          telemetry=config,
      )

      assert shutdowns == [True]


  @pytest.mark.asyncio
  async def test_run_primitive_plan_with_telemetry_does_not_mutate_global_tracer_provider(
      tmp_path: Path,
  ) -> None:
      """The runner must NOT call trace.set_tracer_provider — that would be a
      process-global mutation that breaks concurrent or sequential runs in the
      same process."""
      from opentelemetry import trace as otel_trace

      before = otel_trace.get_tracer_provider()

      config = TelemetryConfig(
          otlp_endpoint="http://localhost:5000/v1/traces",
          otlp_headers={},
          service_name="archipelago-test",
      )
      plan = PrimitivePlan(root=_action())

      await run_primitive_plan(
          plan,
          initial_state=_In(),
          artifacts_dir=tmp_path,
          workspace_volume="vol",
          base_image_tag="img",
          responder_provider=lambda _id: lambda *a, **k: None,
          run_id="r-no-global",
          telemetry=config,
      )

      after = otel_trace.get_tracer_provider()
      assert after is before, (
          "Runner must not mutate the global tracer provider; install per-run on RunContext"
      )


  @pytest.mark.asyncio
  async def test_run_primitive_plan_cleans_up_run_dir_when_build_tracer_provider_raises(
      tmp_path: Path, monkeypatch
  ) -> None:
      """If build_tracer_provider raises, the bootstrapped run_dir must be
      cleaned up so failed runs don't leak directories on disk."""
      from agent_foundry.telemetry import setup as setup_mod

      def boom(_cfg):
          raise RuntimeError("bad telemetry config")

      monkeypatch.setattr(setup_mod, "build_tracer_provider", boom)

      config = TelemetryConfig(
          otlp_endpoint="http://localhost:5000/v1/traces",
          otlp_headers={},
          service_name="archipelago-test",
      )
      plan = PrimitivePlan(root=_action())

      with pytest.raises(RuntimeError, match="bad telemetry config"):
          await run_primitive_plan(
              plan,
              initial_state=_In(),
              artifacts_dir=tmp_path,
              workspace_volume="vol",
              base_image_tag="img",
              responder_provider=lambda _id: lambda *a, **k: None,
              run_id="r-cleanup",
              telemetry=config,
          )

      # No run_dir for r-cleanup should exist under tmp_path
      leaked = list(tmp_path.glob("*r-cleanup*"))
      assert leaked == [], f"Expected no leaked run_dir; found: {leaked}"
  ```

- [ ] **Step 2: Run the failing test.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/orchestration/test_runner_telemetry.py
  ```
  Expected: FAIL with `TypeError: run_primitive_plan() got an unexpected keyword argument 'telemetry'`.

- [ ] **Step 3: Add `telemetry` parameter and per-run provider plumbing to the runner.**

  Edit `src/agent_foundry/orchestration/runner.py`. Critical correctness point: **the runner must NOT call `trace.set_tracer_provider`**. That call mutates process-global state with no undo path; sequential or concurrent runs would silently overwrite each other's providers and drop spans. Instead, the provider is built per run, anchored on `RunContext.telemetry_provider`, and shut down per run. Compiler-side `emit_span` reads the provider from `current_run_context.get().telemetry_provider`.

  ```python
  from agent_foundry.telemetry import TelemetryConfig
  from agent_foundry.telemetry.setup import build_tracer_provider


  async def run_primitive_plan(
      plan: PrimitivePlan,
      *,
      initial_state: BaseModel,
      artifacts_dir: Path,
      workspace_volume: str,
      base_image_tag: str,
      responder_provider: ResponderProvider,
      run_id: str | None = None,
      on_open: list[Callable[..., None]] | None = None,
      on_close: list[Callable[..., None]] | None = None,
      telemetry: TelemetryConfig | None = None,
  ) -> BaseModel:
      """... existing docstring ...

      :param telemetry: When provided, AF builds a per-run OTel TracerProvider
          from the config, anchors it on ``RunContext.telemetry_provider``, and
          shuts it down at run exit. The provider is NEVER installed as the OTel
          process-global tracer-provider — concurrent or sequential runs in the
          same process each have their own provider. Absence (``None``) disables
          telemetry entirely.
      """
      ...

      # Build the provider BEFORE constructing RunContext (so the context can
      # carry it). Wrap the construction in try/except: if the constructor
      # raises (e.g. bad endpoint URL fails OTLPSpanExporter init), we must
      # clean up the already-bootstrapped run_dir before propagating so
      # failed runs don't leak directories on disk.
      import shutil

      provider = None
      if telemetry is not None:
          try:
              provider = build_tracer_provider(telemetry)
          except Exception:
              shutil.rmtree(run_dir, ignore_errors=True)
              raise

      run_ctx = RunContext(
          run_id=resolved_run_id,
          ...,
          telemetry=telemetry,                # added on RunContext (next step)
          telemetry_provider=provider,        # added on RunContext (next step)
      )
      ...

      try:
          ...
      finally:
          # existing teardown (registry.shutdown_all, render_summary) — each guarded ...
          if provider is not None:
              try:
                  provider.shutdown()
              except Exception:
                  logger.warning("TracerProvider.shutdown raised during teardown", exc_info=True)
  ```

  The `try/except` around `provider.shutdown()` matches the existing teardown pattern (`registry.shutdown_all` and `render_summary` are each guarded with `logger.warning` on exception). Without this guard, a hung OTLP exporter or unreachable backend during span flush would mask the original run exception.

  Edit `src/agent_foundry/orchestration/run_context.py` to add the `telemetry` and `telemetry_provider` fields:

  ```python
  from agent_foundry.telemetry import TelemetryConfig
  from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider

  class RunContext(BaseModel):
      ...
      telemetry: TelemetryConfig | None = None
      """Active telemetry config for this run, or None if telemetry is disabled.
      Read by compiler nodes to find redaction policy and run-id binding."""

      telemetry_provider: SDKTracerProvider | None = None
      """Per-run OTel TracerProvider, or None if telemetry is disabled.

      Per-run isolation: each ``run_primitive_plan`` invocation builds its own
      provider and stores it here. ``emit_span`` resolves the active
      ``RunContext.telemetry_provider`` via the ContextVar — no process-global
      tracer-provider state is touched. This is what makes concurrent runs in
      the same process safe.
      """
  ```

  ```python
  redaction = (
      run_ctx.telemetry.redaction
      if run_ctx.telemetry is not None
      else None
  )

  with emit_span(
      name=...,
      ...,
      redaction=redaction,
  ) as handle:
      ...
  ```

  B5 used `getattr(run_ctx, "telemetry", None)` so the code degraded to `None` when the field didn't yet exist; now that B6 adds the field the access can be direct.

- [ ] **Step 4: Run the new tests.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/orchestration/test_runner_telemetry.py
  ```
  Expected: 4 PASSED (including the no-global-mutation test).

- [ ] **Step 5: Run the full test suite.**

  Run:
  ```bash
  pdm test-all
  ```
  Expected: PASS.

- [ ] **Step 6: Lint and typecheck.**

  Run:
  ```bash
  pdm lint
  pdm typecheck
  ```
  Expected: both PASS.

- [ ] **Step 7: Commit.**

  ```bash
  git add src/agent_foundry/orchestration/runner.py \
          src/agent_foundry/orchestration/run_context.py \
          src/agent_foundry/compiler/primitive_compiler.py \
          tests/agent_foundry/orchestration/test_runner_telemetry.py
  git commit -m "feat(runtime): thread TelemetryConfig through run_primitive_plan"
  ```

---

## Phase C — Redaction

### Task C1: Apply `RedactionPolicy` to span input/output (full coverage)

**Files:**
- Modify: `src/agent_foundry/telemetry/spans.py` (existing redaction wiring already present from B4 — add error-case coverage)
- Create: `tests/agent_foundry/telemetry/test_redaction.py`

**Dependencies:** Requires Task B4 only. (C1 tests `emit_span` directly via `InMemorySpanExporter` — it doesn't go through the runner or the compiler, so it doesn't depend on B6's threading.)

- [ ] **Step 1: Write the failing test.**

  Create `tests/agent_foundry/telemetry/test_redaction.py`:

  ```python
  """Tests for RedactionPolicy applied to emit_span."""

  from __future__ import annotations

  import asyncio
  import json
  from pathlib import Path

  import pytest
  from opentelemetry.sdk.trace import TracerProvider
  from opentelemetry.sdk.trace.export import SimpleSpanProcessor
  from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
  from pydantic import BaseModel

  from agent_foundry.orchestration.run_context import (
      NoOpLifecycleWriter,
      RunContext,
      current_run_context,
  )
  from agent_foundry.telemetry import attributes
  from agent_foundry.telemetry.config import RedactionPolicy
  from agent_foundry.telemetry.spans import emit_span


  class _Sensitive(BaseModel):
      ticket_id: str
      api_key: str


  @pytest.fixture()
  def exporter(tmp_path: Path):
      exp = InMemorySpanExporter()
      provider = TracerProvider()
      provider.add_span_processor(SimpleSpanProcessor(exp))
      ctx = RunContext(
          run_id="test-redaction",
          artifacts_dir=tmp_path,
          container_registry=object(),
          responder_provider=object(),
          lifecycle_writer=NoOpLifecycleWriter(),
          cancel_event=asyncio.Event(),
          env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
          telemetry_provider=provider,
      )
      token = current_run_context.set(ctx)
      try:
          yield exp
      finally:
          current_run_context.reset(token)
          provider.shutdown()


  def test_redact_input_replaces_sensitive_field_in_span_attribute(exporter) -> None:
      exporter.clear()
      policy = RedactionPolicy(
          redact_input=lambda m: _Sensitive(ticket_id=m.ticket_id, api_key="[REDACTED]"),
      )

      with emit_span(
          name="primitive",
          primitive_type="X",
          primitive_name=None,
          input_model=_Sensitive(ticket_id="1", api_key="sk-real"),
          run_id=None,
          redaction=policy,
      ) as handle:
          handle.set_output(_Sensitive(ticket_id="1", api_key="sk-real"))

      span = exporter.get_finished_spans()[0]
      payload = json.loads(span.attributes[attributes.AF_INPUT])
      assert payload["api_key"] == "[REDACTED]"
      assert payload["ticket_id"] == "1"


  def test_redact_output_replaces_sensitive_field_in_span_attribute(exporter) -> None:
      exporter.clear()
      policy = RedactionPolicy(
          redact_output=lambda m: _Sensitive(ticket_id=m.ticket_id, api_key="[REDACTED]"),
      )

      with emit_span(
          name="primitive",
          primitive_type="X",
          primitive_name=None,
          input_model=_Sensitive(ticket_id="1", api_key="sk-real"),
          run_id=None,
          redaction=policy,
      ) as handle:
          handle.set_output(_Sensitive(ticket_id="1", api_key="sk-real"))

      span = exporter.get_finished_spans()[0]
      payload = json.loads(span.attributes[attributes.AF_OUTPUT])
      assert payload["api_key"] == "[REDACTED]"


  def test_redact_input_returning_non_basemodel_raises(exporter) -> None:
      exporter.clear()
      policy = RedactionPolicy(
          redact_input=lambda m: {"not": "a basemodel"},  # type: ignore[return-value]
      )

      with pytest.raises(TypeError, match="redact_input must return a Pydantic BaseModel"):
          with emit_span(
              name="primitive",
              primitive_type="X",
              primitive_name=None,
              input_model=_Sensitive(ticket_id="1", api_key="sk"),
              run_id=None,
              redaction=policy,
          ):
              pass


  def test_no_redaction_policy_passes_input_through_unchanged(exporter) -> None:
      exporter.clear()
      with emit_span(
          name="primitive",
          primitive_type="X",
          primitive_name=None,
          input_model=_Sensitive(ticket_id="1", api_key="sk-real"),
          run_id=None,
          redaction=None,
      ) as handle:
          handle.set_output(_Sensitive(ticket_id="1", api_key="sk-real"))

      span = exporter.get_finished_spans()[0]
      payload = json.loads(span.attributes[attributes.AF_INPUT])
      assert payload["api_key"] == "sk-real"
  ```

- [ ] **Step 2: Run the test.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/telemetry/test_redaction.py
  ```
  Expected: tests PASS for the success cases (already wired in B4); the `TypeError` test should fail if the type-check raise is missing — check the exact failure mode:
  - If B4 already raises the `TypeError`: 4 PASSED.
  - If not: implement the error path in the next step.

- [ ] **Step 3: Confirm the error path is wired (no implementation change if B4 already covered it).**

  Re-read `src/agent_foundry/telemetry/spans.py` and confirm:
  - `redact_input` callable validated with `isinstance(redacted_input, BaseModel)` and raises `TypeError` if not.
  - Same check on `set_output` for `redact_output`.

  If either check is missing, add it (the implementation already shown in B4 includes both checks).

- [ ] **Step 4: Run all redaction tests.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/telemetry/test_redaction.py
  ```
  Expected: 4 PASSED.

- [ ] **Step 5: Lint and typecheck.**

  Run:
  ```bash
  pdm lint
  pdm typecheck
  ```
  Expected: both PASS.

- [ ] **Step 6: Commit.**

  ```bash
  git add src/agent_foundry/telemetry/spans.py \
          tests/agent_foundry/telemetry/test_redaction.py
  git commit -m "feat(telemetry): apply RedactionPolicy to span input/output"
  ```

---

## Phase D — MLflow adapter

### Task D1: `mlflow_adapter` skeleton with import guard

**Files:**
- Create: `src/agent_foundry/mlflow_adapter/__init__.py`
- Create: `src/agent_foundry/mlflow_adapter/extras.py`
- Create: `tests/agent_foundry/mlflow_adapter/__init__.py`
- Create: `tests/agent_foundry/mlflow_adapter/test_extras.py`

**Dependencies:** Requires Task A4.

The import-guard logic lives in `extras.py` (matches design's File Layout); `__init__.py` imports from it. Splitting them lets future code that wants to defer the guard check have a single load point to consult.

- [ ] **Step 1: Write the failing test.**

  Create `tests/agent_foundry/mlflow_adapter/__init__.py` (empty file).

  Create `tests/agent_foundry/mlflow_adapter/test_extras.py`:

  ```python
  """Tests for the mlflow_adapter import guard."""

  from __future__ import annotations

  import sys

  import pytest


  def test_mlflow_adapter_import_succeeds_when_mlflow_is_available() -> None:
      # mlflow is installed via the [mlflow] extra; just confirm the package
      # imports without error.
      import agent_foundry.mlflow_adapter  # noqa: F401


  def test_mlflow_adapter_import_raises_helpful_error_when_mlflow_missing(
      monkeypatch: pytest.MonkeyPatch,
  ) -> None:
      # Force ImportError on `import mlflow` and confirm the adapter raises the
      # actionable message.
      mod_name = "agent_foundry.mlflow_adapter"
      sys.modules.pop(mod_name, None)
      monkeypatch.setitem(sys.modules, "mlflow", None)

      with pytest.raises(ImportError, match=r"\[mlflow\] extra"):
          __import__(mod_name)
  ```

- [ ] **Step 2: Run the failing test.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/mlflow_adapter/test_extras.py
  ```
  Expected: FAIL with `ModuleNotFoundError: No module named 'agent_foundry.mlflow_adapter'`.

- [ ] **Step 3: Create `extras.py` with the import guard.**

  Create `src/agent_foundry/mlflow_adapter/extras.py`:

  ```python
  """Optional-dependency import guard for the MLflow adapter.

  Raises a helpful ImportError when the ``[mlflow]`` extra is not installed.
  The adapter's other modules import from this file so the error surfaces
  uniformly regardless of which entry point the user hit first.
  """

  from __future__ import annotations

  try:
      import mlflow  # noqa: F401
  except ImportError as exc:
      raise ImportError(
          "agent_foundry.mlflow_adapter requires the [mlflow] extra. "
          "Install with: pip install agent-foundry[mlflow]"
      ) from exc
  ```

- [ ] **Step 4: Create the package `__init__.py` that triggers the guard.**

  Create `src/agent_foundry/mlflow_adapter/__init__.py`:

  ```python
  """MLflow adapter for Agent Foundry telemetry.

  Translates AF's ``agent_foundry.*`` span attributes additively to MLflow's
  ``mlflow.*`` namespace, and binds MLflow Run lifecycle to ``RunContext``
  open/close hooks.

  Optional install — requires the ``[mlflow]`` extra:

      pip install agent-foundry[mlflow]
  """

  from __future__ import annotations

  # Import-guard (raises actionable ImportError if mlflow isn't installed).
  from agent_foundry.mlflow_adapter import extras  # noqa: F401

  __all__: list[str] = []
  ```

- [ ] **Step 5: Run the tests.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/mlflow_adapter/test_extras.py
  ```
  Expected: 2 PASSED.

- [ ] **Step 6: Lint and typecheck.**

  Run:
  ```bash
  pdm lint
  pdm typecheck
  ```
  Expected: both PASS.

- [ ] **Step 7: Commit.**

  ```bash
  git add src/agent_foundry/mlflow_adapter/__init__.py \
          src/agent_foundry/mlflow_adapter/extras.py \
          tests/agent_foundry/mlflow_adapter/__init__.py \
          tests/agent_foundry/mlflow_adapter/test_extras.py
  git commit -m "feat(mlflow): add adapter skeleton with optional-dep import guard"
  ```

---

### Task D2: `MLFLOW_TRANSLATIONS` constant + emit-time translation tests

**Files:**
- Create: `src/agent_foundry/mlflow_adapter/translation.py`
- Create: `tests/agent_foundry/mlflow_adapter/test_translation.py`

**Dependencies:** Requires Tasks B2, B4, D1.

**Architecture note** (changed in pass-3 review): the original draft of this task added a `SpanProcessor` that mutated span attributes during `on_end`. That doesn't work — OTel SDK calls `span.end()` *before* `on_end` callbacks, and `_check_span_ended` makes any subsequent `set_attribute` a no-op. The translation processor would silently drop every translated attribute under `BatchSpanProcessor` (the production pipeline).

The fix: translation happens at **emit time**, inside `emit_span`. The MLflow adapter exports a constant translation table that products plug into `TelemetryConfig.attribute_translations`. AF core stays MLflow-agnostic — it just dual-writes per a generic table. No SpanProcessor is needed.

- [ ] **Step 1: Write the failing test.**

  Create `tests/agent_foundry/mlflow_adapter/test_translation.py`:

  ```python
  """Tests for MLFLOW_TRANSLATIONS constant and emit-time mirroring."""

  from __future__ import annotations

  import asyncio
  import json
  from pathlib import Path

  import pytest
  from opentelemetry.sdk.trace import TracerProvider
  from opentelemetry.sdk.trace.export import SimpleSpanProcessor
  from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
  from pydantic import BaseModel

  from agent_foundry.mlflow_adapter.translation import MLFLOW_TRANSLATIONS
  from agent_foundry.orchestration.run_context import (
      NoOpLifecycleWriter,
      RunContext,
      current_run_context,
  )
  from agent_foundry.telemetry import attributes
  from agent_foundry.telemetry.config import TelemetryConfig
  from agent_foundry.telemetry.spans import emit_span


  class _M(BaseModel):
      x: int


  def test_mlflow_translations_constant_shape() -> None:
      assert MLFLOW_TRANSLATIONS["agent_foundry.input"] == "mlflow.spanInputs"
      assert MLFLOW_TRANSLATIONS["agent_foundry.output"] == "mlflow.spanOutputs"


  @pytest.fixture()
  def telemetry_ctx(tmp_path: Path):
      """RunContext with a TracerProvider and the MLflow translation table."""
      exporter = InMemorySpanExporter()
      provider = TracerProvider()
      provider.add_span_processor(SimpleSpanProcessor(exporter))
      config = TelemetryConfig(
          otlp_endpoint="http://localhost:5000/v1/traces",
          otlp_headers={},
          service_name="t",
          attribute_translations=MLFLOW_TRANSLATIONS,
      )
      ctx = RunContext(
          run_id="t-translation",
          artifacts_dir=tmp_path,
          container_registry=object(),
          responder_provider=object(),
          lifecycle_writer=NoOpLifecycleWriter(),
          cancel_event=asyncio.Event(),
          env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
          telemetry=config,
          telemetry_provider=provider,
      )
      tok = current_run_context.set(ctx)
      try:
          yield exporter
      finally:
          current_run_context.reset(tok)
          provider.shutdown()


  def test_emit_span_dual_writes_input_and_output_via_mlflow_translations(
      telemetry_ctx,
  ) -> None:
      """Both agent_foundry.* and mlflow.* attributes land on the same span,
      written before span.end() — neither lost to OTel's set-after-end no-op.
      """
      with emit_span(
          name="agent_foundry.X",
          primitive_type="X",
          primitive_name=None,
          input_model=_M(x=1),
          run_id=None,
          redaction=None,
      ) as handle:
          handle.set_output(_M(x=2))

      span = telemetry_ctx.get_finished_spans()[0]
      assert json.loads(span.attributes[attributes.AF_INPUT]) == {"x": 1}
      assert json.loads(span.attributes[attributes.AF_OUTPUT]) == {"x": 2}
      assert json.loads(span.attributes["mlflow.spanInputs"]) == {"x": 1}
      assert json.loads(span.attributes["mlflow.spanOutputs"]) == {"x": 2}


  def test_emit_span_without_translations_does_not_set_mlflow_attributes(
      tmp_path: Path,
  ) -> None:
      """If the product opts out of translation by leaving the table empty,
      AF emits only its own ``agent_foundry.*`` namespace."""
      exporter = InMemorySpanExporter()
      provider = TracerProvider()
      provider.add_span_processor(SimpleSpanProcessor(exporter))
      config = TelemetryConfig(
          otlp_endpoint="http://localhost:5000/v1/traces",
          otlp_headers={},
          service_name="t",
          # attribute_translations defaults to {}
      )
      ctx = RunContext(
          run_id="t-no-trans",
          artifacts_dir=tmp_path,
          container_registry=object(),
          responder_provider=object(),
          lifecycle_writer=NoOpLifecycleWriter(),
          cancel_event=asyncio.Event(),
          env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
          telemetry=config,
          telemetry_provider=provider,
      )
      tok = current_run_context.set(ctx)
      try:
          with emit_span(
              name="x",
              primitive_type="X",
              primitive_name=None,
              input_model=_M(x=1),
              run_id=None,
              redaction=None,
          ) as handle:
              handle.set_output(_M(x=2))
      finally:
          current_run_context.reset(tok)
          provider.shutdown()

      span = exporter.get_finished_spans()[0]
      assert "mlflow.spanInputs" not in span.attributes
      assert "mlflow.spanOutputs" not in span.attributes
  ```

- [ ] **Step 2: Run the failing test.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/mlflow_adapter/test_translation.py
  ```
  Expected: FAIL with `ModuleNotFoundError: No module named 'agent_foundry.mlflow_adapter.translation'`.

- [ ] **Step 3: Create the translation table constant.**

  Create `src/agent_foundry/mlflow_adapter/translation.py`:

  ```python
  """Translation table mapping AF span-attribute names to MLflow attribute names.

  This module exports a constant ``dict`` rather than a ``SpanProcessor``.
  Translation happens at attribute-set time inside ``emit_span`` (see
  ``agent_foundry/telemetry/spans.py``), not after the span ends — OTel's
  SDK makes ``set_attribute`` a no-op on ended spans, so a post-end
  SpanProcessor approach silently drops translated attributes under
  ``BatchSpanProcessor`` (the production pipeline).

  Products plug this table into ``TelemetryConfig.attribute_translations``
  to opt into MLflow-compatible attribute mirroring. AF core stays
  MLflow-agnostic — it just dual-writes per the table.
  """

  MLFLOW_TRANSLATIONS: dict[str, str] = {
      "agent_foundry.input": "mlflow.spanInputs",
      "agent_foundry.output": "mlflow.spanOutputs",
  }
  ```

  Re-export from `__init__.py`:

  ```python
  from agent_foundry.mlflow_adapter.translation import MLFLOW_TRANSLATIONS

  __all__ = ["enable", "reset_for_testing", "MLFLOW_TRANSLATIONS"]
  ```

- [ ] **Step 4: Run the tests.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/mlflow_adapter/test_translation.py
  ```
  Expected: 3 PASSED.

- [ ] **Step 5: Lint and typecheck.**

  Run:
  ```bash
  pdm lint
  pdm typecheck
  ```
  Expected: both PASS.

- [ ] **Step 6: Commit.**

  ```bash
  git add src/agent_foundry/mlflow_adapter/translation.py \
          src/agent_foundry/mlflow_adapter/__init__.py \
          tests/agent_foundry/mlflow_adapter/test_translation.py
  git commit -m "feat(mlflow): MLFLOW_TRANSLATIONS table; translation at emit time, not span-end"
  ```

---

### Task D3: Run lifecycle hooks

**Files:**
- Create: `src/agent_foundry/mlflow_adapter/run_lifecycle.py`
- Create: `tests/agent_foundry/mlflow_adapter/test_run_lifecycle.py`

**Dependencies:** Requires Tasks A3, B1, D1.

- [ ] **Step 1: Write the failing test.**

  Create `tests/agent_foundry/mlflow_adapter/test_run_lifecycle.py`:

  ```python
  """Tests for the MLflow run lifecycle hooks."""

  from __future__ import annotations

  import asyncio
  from pathlib import Path
  from types import SimpleNamespace
  from typing import Any

  import pytest
  from pydantic import BaseModel

  from agent_foundry.mlflow_adapter.run_lifecycle import attach_run_hooks
  from agent_foundry.orchestration.run_context import (
      NoOpLifecycleWriter,
      RunContext,
  )
  from agent_foundry.telemetry.config import (
      ArtifactSpec,
      RedactionPolicy,
      RunDefinition,
      RunStats,
  )


  class _In(BaseModel):
      ticket_id: str = "42"


  class _Out(BaseModel):
      success: bool = True


  class FakeMLflow:
      def __init__(self) -> None:
          self.start_run_calls: list[dict[str, Any]] = []
          self.log_params_calls: list[dict[str, Any]] = []
          self.log_metrics_calls: list[dict[str, Any]] = []
          self.log_artifact_calls: list[tuple[str, str | None]] = []
          self.end_run_calls: list[str] = []
          self._next_run_id = "mlflow-run-1"

      def start_run(self, run_name: str, tags: dict[str, str]) -> SimpleNamespace:
          self.start_run_calls.append({"run_name": run_name, "tags": tags})
          return SimpleNamespace(info=SimpleNamespace(run_id=self._next_run_id))

      def log_params(self, params: dict[str, Any]) -> None:
          self.log_params_calls.append(params)

      def log_metrics(self, metrics: dict[str, float]) -> None:
          self.log_metrics_calls.append(metrics)

      def log_artifact(self, local_path: str, artifact_path: str | None = None) -> None:
          self.log_artifact_calls.append((local_path, artifact_path))

      def end_run(self, status: str = "FINISHED") -> None:
          self.end_run_calls.append(status)


  @pytest.fixture()
  def fake_mlflow(monkeypatch: pytest.MonkeyPatch) -> FakeMLflow:
      fake = FakeMLflow()
      import agent_foundry.mlflow_adapter.run_lifecycle as mod

      monkeypatch.setattr(mod, "mlflow", fake, raising=False)
      return fake


  def _ctx(tmp_path: Path) -> RunContext:
      return RunContext(
          run_id="r",
          artifacts_dir=tmp_path,
          container_registry=object(),
          responder_provider=object(),
          lifecycle_writer=NoOpLifecycleWriter(),
          cancel_event=asyncio.Event(),
          env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
      )


  def _run_def() -> RunDefinition:
      return RunDefinition(
          name=lambda inp: f"ticket-{inp.ticket_id}",
          params=lambda inp: {"ticket_id": inp.ticket_id},
          tags={"product": "archipelago"},
          metrics=lambda out, stats: (
              {"duration_ms": stats.duration_ms, "success": float(out.success)}
              if out is not None
              else {"duration_ms": stats.duration_ms}
          ),
      )


  def test_on_open_starts_run_and_logs_params(fake_mlflow, tmp_path: Path) -> None:
      ctx = _ctx(tmp_path)
      attach_run_hooks(
          run_context=ctx,
          run_definition=_run_def(),
          redaction=None,
          input_model=_In(ticket_id="42"),
      )

      for hook in ctx.on_open:
          hook(ctx)

      assert fake_mlflow.start_run_calls == [
          {"run_name": "ticket-42", "tags": {"product": "archipelago"}}
      ]
      assert fake_mlflow.log_params_calls == [{"ticket_id": "42"}]


  def test_on_close_logs_metrics_with_output_and_ends_run_finished(
      fake_mlflow, tmp_path: Path
  ) -> None:
      ctx = _ctx(tmp_path)
      attach_run_hooks(
          run_context=ctx,
          run_definition=_run_def(),
          redaction=None,
          input_model=_In(ticket_id="42"),
      )
      output = _Out(success=True)

      for hook in ctx.on_open:
          hook(ctx)
      for hook in ctx.on_close:
          hook(ctx, None, output)

      assert len(fake_mlflow.log_metrics_calls) == 1
      logged = fake_mlflow.log_metrics_calls[0]
      assert "duration_ms" in logged
      # success was read off the OUTPUT model, not the input
      assert logged["success"] == 1.0
      assert fake_mlflow.end_run_calls == ["FINISHED"]


  def test_on_close_with_exception_and_none_output_ends_run_failed(
      fake_mlflow, tmp_path: Path
  ) -> None:
      ctx = _ctx(tmp_path)
      attach_run_hooks(
          run_context=ctx,
          run_definition=_run_def(),
          redaction=None,
          input_model=_In(ticket_id="42"),
      )

      for hook in ctx.on_open:
          hook(ctx)
      for hook in ctx.on_close:
          hook(ctx, RuntimeError("boom"), None)

      assert fake_mlflow.end_run_calls == ["FAILED"]
      # metrics was called with output=None — the run_def gracefully degrades
      assert len(fake_mlflow.log_metrics_calls) == 1
      assert "success" not in fake_mlflow.log_metrics_calls[0]


  def test_on_close_calls_end_run_even_when_metrics_callable_raises(
      fake_mlflow, tmp_path: Path
  ) -> None:
      """Undefended metrics callable raise (e.g. AttributeError on out.success
      when out is None) must NOT orphan the MLflow run in RUNNING state."""
      ctx = _ctx(tmp_path)
      bad_run_def = RunDefinition(
          name=lambda inp: "n",
          params=lambda inp: {},
          tags={},
          metrics=lambda out, stats: {"success": float(out.success)},  # crashes if out is None
      )
      attach_run_hooks(
          run_context=ctx,
          run_definition=bad_run_def,
          redaction=None,
          input_model=_In(ticket_id="42"),
      )

      for hook in ctx.on_open:
          hook(ctx)
      for hook in ctx.on_close:
          hook(ctx, RuntimeError("plan failed"), None)  # output is None on failure

      # end_run was called despite the metrics callable raising
      assert fake_mlflow.end_run_calls == ["FAILED"]


  def test_on_close_treats_partial_open_as_failed(
      fake_mlflow, tmp_path: Path, caplog: pytest.LogCaptureFixture
  ) -> None:
      """If on_open's mlflow.log_params raises after start_run succeeds, on_close
      must still close the run with FAILED status (no orphan)."""
      original_log_params = fake_mlflow.log_params

      def boom_log_params(*a, **k):
          raise RuntimeError("log_params failed")

      fake_mlflow.log_params = boom_log_params  # type: ignore[method-assign]

      ctx = _ctx(tmp_path)
      attach_run_hooks(
          run_context=ctx,
          run_definition=_run_def(),
          redaction=None,
          input_model=_In(ticket_id="42"),
      )

      # log_params will raise inside on_open; in production _safe_invoke_hooks
      # swallows. Here we call directly and catch.
      for hook in ctx.on_open:
          try:
              hook(ctx)
          except RuntimeError:
              pass

      for hook in ctx.on_close:
          hook(ctx, None, _Out(success=True))

      # The run was started, so on_close must close it — but as FAILED because
      # the open was incomplete (open_clean stayed False).
      assert fake_mlflow.end_run_calls == ["FAILED"]
      # log_metrics AND log_artifact are skipped because open_clean is False
      # (params are unreliable, so derived data is not trusted).
      assert fake_mlflow.log_metrics_calls == []
      assert fake_mlflow.log_artifact_calls == []


  def test_on_close_skipped_when_on_open_did_not_start_run(
      fake_mlflow, tmp_path: Path, caplog: pytest.LogCaptureFixture
  ) -> None:
      """If on_open's mlflow.start_run raised, on_close must not call MLflow APIs."""
      import logging

      def boom_start_run(*a, **k):
          raise RuntimeError("mlflow start_run failed")

      fake_mlflow.start_run = boom_start_run  # type: ignore[method-assign]

      ctx = _ctx(tmp_path)
      attach_run_hooks(
          run_context=ctx,
          run_definition=_run_def(),
          redaction=None,
          input_model=_In(ticket_id="42"),
      )

      # on_open hook will raise; in production _safe_invoke_hooks swallows.
      # Here we call the hooks directly and catch.
      for hook in ctx.on_open:
          try:
              hook(ctx)
          except RuntimeError:
              pass

      with caplog.at_level(logging.WARNING):
          for hook in ctx.on_close:
              hook(ctx, None, _Out(success=True))

      # No MLflow API calls beyond the failed start_run attempt
      assert fake_mlflow.log_metrics_calls == []
      assert fake_mlflow.log_artifact_calls == []
      assert fake_mlflow.end_run_calls == []
      # And a warning was logged so the silent skip isn't truly silent
      assert any("on_close skipped" in record.message for record in caplog.records)


  def test_on_open_applies_redaction_to_params(fake_mlflow, tmp_path: Path) -> None:
      ctx = _ctx(tmp_path)
      policy = RedactionPolicy(
          redact_input=lambda m: _In(ticket_id="[REDACTED]"),
      )
      attach_run_hooks(
          run_context=ctx,
          run_definition=_run_def(),
          redaction=policy,
          input_model=_In(ticket_id="42"),
      )

      for hook in ctx.on_open:
          hook(ctx)

      assert fake_mlflow.log_params_calls == [{"ticket_id": "[REDACTED]"}]


  def test_on_close_logs_artifacts(fake_mlflow, tmp_path: Path) -> None:
      ctx = _ctx(tmp_path)
      artifact_path = tmp_path / "result.json"
      artifact_path.write_text("{}")

      run_def = RunDefinition(
          name=lambda _: "n",
          params=lambda _: {},
          tags={},
          metrics=lambda _out, _s: {"x": 1.0},
          artifacts=[ArtifactSpec(path=artifact_path, artifact_path="results")],
      )
      attach_run_hooks(
          run_context=ctx,
          run_definition=run_def,
          redaction=None,
          input_model=_In(),
      )

      for hook in ctx.on_open:
          hook(ctx)
      for hook in ctx.on_close:
          hook(ctx, None, _Out(success=True))

      assert fake_mlflow.log_artifact_calls == [(str(artifact_path), "results")]
  ```

- [ ] **Step 2: Run the failing test.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/mlflow_adapter/test_run_lifecycle.py
  ```
  Expected: FAIL with `ModuleNotFoundError: No module named 'agent_foundry.mlflow_adapter.run_lifecycle'`.

- [ ] **Step 3: Implement the lifecycle hooks.**

  Create `src/agent_foundry/mlflow_adapter/run_lifecycle.py`:

  ```python
  """Bind MLflow Run lifecycle to RunContext open/close hooks."""

  from __future__ import annotations

  import time
  from typing import Any

  import mlflow
  from pydantic import BaseModel

  from agent_foundry.orchestration.run_context import RunContext
  from agent_foundry.telemetry.config import (
      RedactionPolicy,
      RunDefinition,
      RunStats,
  )


  def _resolve_tags(
      tags: dict[str, str] | Any, input_model: BaseModel
  ) -> dict[str, str]:
      if callable(tags):
          return tags(input_model)
      return dict(tags)


  def attach_run_hooks(
      *,
      run_context: RunContext,
      run_definition: RunDefinition,
      redaction: RedactionPolicy | None,
      input_model: BaseModel,
  ) -> None:
      """Append open/close callables to ``run_context`` that drive an MLflow Run.

      On open: evaluates ``run_definition.name`` / ``params`` / ``tags`` against
      ``input_model`` (with optional redaction applied to params), calls
      ``mlflow.start_run``, and logs the params. If any of these raises, the
      exception propagates to ``_safe_invoke_hooks`` which logs and continues —
      ``state["mlflow_run_id"]`` stays None and the on_close hook will become
      a no-op.

      On close: if on_open did not successfully start an MLflow run, this is
      a no-op (a warning is logged). Otherwise builds a ``RunStats``, evaluates
      ``run_definition.metrics(output, stats)`` against the run's final
      OUTPUT (or None on failure), logs metrics + artifacts, and ends the
      MLflow run with status FINISHED on success or FAILED if an exception
      was raised.
      """
      state: dict[str, Any] = {
          "start_time": None,
          "mlflow_run_id": None,
          "open_clean": False,
      }

      def on_open(_ctx: RunContext) -> None:
          state["start_time"] = time.monotonic()
          name = run_definition.name(input_model)
          tags = _resolve_tags(run_definition.tags, input_model)

          # Redact the input before evaluating params so secrets never reach mlflow
          params_input = input_model
          if redaction is not None and redaction.redact_input is not None:
              params_input = redaction.redact_input(input_model)
          params = run_definition.params(params_input)

          run = mlflow.start_run(run_name=name, tags=tags)
          # Set mlflow_run_id ONLY after start_run succeeds — on_close uses this
          # as a guard. open_clean stays False until log_params also succeeds.
          state["mlflow_run_id"] = run.info.run_id
          mlflow.log_params(params)
          state["open_clean"] = True

      def on_close(
          _ctx: RunContext, exc: BaseException | None, output: BaseModel | None
      ) -> None:
          if state["mlflow_run_id"] is None:
              # on_open failed before start_run succeeded — no MLflow run to
              # close. Log a warning so the silent skip isn't truly silent.
              logger.warning(
                  "MLflow on_close skipped — on_open did not start a run "
                  "(likely mlflow.start_run raised). Spans were emitted but "
                  "no MLflow Run wraps them."
              )
              return

          # If on_open partially succeeded (start_run ran but log_params raised),
          # treat the run as FAILED regardless of the actual run outcome — the
          # open was incomplete, the recorded params are unreliable. Still close
          # the run so it doesn't orphan in RUNNING state.
          status = "FAILED" if (exc is not None or not state["open_clean"]) else "FINISHED"

          # The end_run call MUST always fire to close the MLflow run, even if
          # log_metrics or log_artifact raise. Use try/finally so an exception in
          # the middle doesn't orphan the run.
          try:
              if state["open_clean"]:
                  duration_ms = (
                      (time.monotonic() - state["start_time"]) * 1000.0
                      if state["start_time"] is not None
                      else 0.0
                  )
                  stats = RunStats(
                      duration_ms=duration_ms,
                      # span_count / token totals are zero in this foundational
                      # scope; see RunStats docstring. Products' metrics callables
                      # must not branch on these fields until span tracking lands.
                  )

                  try:
                      metrics = run_definition.metrics(output, stats)
                      if metrics:
                          mlflow.log_metrics(metrics)
                  except Exception:
                      logger.exception(
                          "RunDefinition.metrics raised; skipping log_metrics. "
                          "MLflow run will still be closed."
                      )
                      status = "FAILED"

                  for spec in run_definition.artifacts:
                      try:
                          mlflow.log_artifact(str(spec.path), spec.artifact_path)
                      except Exception:
                          logger.exception(
                              "log_artifact failed for %s; continuing", spec.path
                          )
                          # Escalate: an artifact failure means the run did
                          # not close cleanly. Match the metrics-failure
                          # pattern.
                          status = "FAILED"
          finally:
              mlflow.end_run(status=status)

      # RunContext is frozen — use ``list.append`` on the existing list (mutable
      # field value) rather than reassigning the field itself.
      run_context.on_open.append(on_open)
      run_context.on_close.append(on_close)
  ```

  Note: also add `import logging` and `logger = logging.getLogger(__name__)` at the top of the module if not already present.

- [ ] **Step 4: Run the tests.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/mlflow_adapter/test_run_lifecycle.py
  ```
  Expected: 5 PASSED.

- [ ] **Step 5: Lint and typecheck.**

  Run:
  ```bash
  pdm lint
  pdm typecheck
  ```
  Expected: both PASS.

- [ ] **Step 6: Commit.**

  ```bash
  git add src/agent_foundry/mlflow_adapter/run_lifecycle.py \
          tests/agent_foundry/mlflow_adapter/test_run_lifecycle.py
  git commit -m "feat(mlflow): bind MLflow Run lifecycle to RunContext hooks"
  ```

---

### Task D4: Public `enable()` adapter wiring

**Files:**
- Modify: `src/agent_foundry/mlflow_adapter/__init__.py`
- Create: `tests/agent_foundry/mlflow_adapter/test_enable.py`

**Dependencies:** Requires Tasks D1, D2, D3, B6.

- [ ] **Step 1: Write the failing test.**

  Create `tests/agent_foundry/mlflow_adapter/test_enable.py`:

  ```python
  """Integration test: enable() wires translation + run lifecycle into one call."""

  from __future__ import annotations

  import asyncio
  from pathlib import Path
  from types import SimpleNamespace
  from typing import Any

  import pytest
  from opentelemetry.sdk.trace import TracerProvider
  from opentelemetry.sdk.trace.export import SimpleSpanProcessor
  from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
  from pydantic import BaseModel

  from agent_foundry.mlflow_adapter import enable
  from agent_foundry.orchestration.run_context import NoOpLifecycleWriter, RunContext
  from agent_foundry.telemetry import attributes
  from agent_foundry.telemetry.config import (
      RunDefinition,
      TelemetryConfig,
  )


  class _In(BaseModel):
      ticket_id: str = "42"


  class FakeMLflow:
      def __init__(self) -> None:
          self.calls: list[tuple[str, dict[str, Any]]] = []

      def start_run(self, run_name: str, tags: dict[str, str]) -> SimpleNamespace:
          self.calls.append(("start_run", {"run_name": run_name, "tags": tags}))
          return SimpleNamespace(info=SimpleNamespace(run_id="m-1"))

      def log_params(self, params: dict[str, Any]) -> None:
          self.calls.append(("log_params", params))

      def log_metrics(self, metrics: dict[str, float]) -> None:
          self.calls.append(("log_metrics", metrics))

      def log_artifact(self, *a, **k) -> None:
          self.calls.append(("log_artifact", {"args": a, "kwargs": k}))

      def end_run(self, status: str = "FINISHED") -> None:
          self.calls.append(("end_run", {"status": status}))


  @pytest.fixture()
  def fake_mlflow(monkeypatch: pytest.MonkeyPatch) -> FakeMLflow:
      fake = FakeMLflow()
      import agent_foundry.mlflow_adapter.run_lifecycle as mod

      monkeypatch.setattr(mod, "mlflow", fake, raising=False)
      return fake


  @pytest.fixture(autouse=True)
  def reset_adapter_state() -> None:
      """Clear the adapter's process-global idempotency sets between tests so
      a provider/context registered in one test doesn't suppress registration
      in the next."""
      from agent_foundry.mlflow_adapter import reset_for_testing

      reset_for_testing()
      yield
      reset_for_testing()


  def _ctx(
      tmp_path: Path,
      run_id: str = "r-default",
      provider: TracerProvider | None = None,
  ) -> RunContext:
      return RunContext(
          run_id=run_id,
          artifacts_dir=tmp_path,
          container_registry=object(),
          responder_provider=object(),
          lifecycle_writer=NoOpLifecycleWriter(),
          cancel_event=asyncio.Event(),
          env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
          telemetry_provider=provider,
      )


  def test_enable_does_not_register_a_span_processor(
      fake_mlflow, tmp_path: Path
  ) -> None:
      """Translation happens via ``TelemetryConfig.attribute_translations``
      at emit time — ``enable()`` must NOT add a SpanProcessor (the previous
      design was broken because OTel's SDK makes ``set_attribute`` a no-op
      after ``span.end()``)."""
      provider = TracerProvider()
      processors_before = list(
          provider._active_span_processor._span_processors  # type: ignore[attr-defined]
      )

      config = TelemetryConfig(
          otlp_endpoint="http://localhost:5000/v1/traces",
          otlp_headers={},
          service_name="archipelago-test",
          run_definition=RunDefinition(
              name=lambda inp: f"ticket-{inp.ticket_id}",
              params=lambda inp: {"ticket_id": inp.ticket_id},
              tags={},
              metrics=lambda _out, _s: {},
          ),
      )
      ctx = _ctx(tmp_path, run_id="r-no-processor", provider=provider)

      enable(config=config, run_context=ctx, input_model=_In(ticket_id="42"))

      processors_after = list(
          provider._active_span_processor._span_processors  # type: ignore[attr-defined]
      )
      assert len(processors_before) == len(processors_after)
      provider.shutdown()


  def test_enable_attaches_run_lifecycle_hooks(fake_mlflow, tmp_path: Path) -> None:
      provider = TracerProvider()

      config = TelemetryConfig(
          otlp_endpoint="http://localhost:5000/v1/traces",
          otlp_headers={},
          service_name="archipelago-test",
          run_definition=RunDefinition(
              name=lambda inp: f"ticket-{inp.ticket_id}",
              params=lambda inp: {"ticket_id": inp.ticket_id},
              tags={},
              metrics=lambda _out, _s: {},
          ),
      )
      ctx = _ctx(tmp_path, run_id="r-hooks", provider=provider)

      enable(config=config, run_context=ctx, input_model=_In(ticket_id="7"))

      assert len(ctx.on_open) == 1
      assert len(ctx.on_close) == 1
      provider.shutdown()


  def test_enable_is_idempotent_for_same_context(fake_mlflow, tmp_path: Path) -> None:
      provider = TracerProvider()

      config = TelemetryConfig(
          otlp_endpoint="http://localhost:5000/v1/traces",
          otlp_headers={},
          service_name="archipelago-test",
          run_definition=RunDefinition(
              name=lambda inp: "n",
              params=lambda inp: {},
              tags={},
              metrics=lambda _out, _s: {},
          ),
      )
      ctx = _ctx(tmp_path, run_id="r-idem", provider=provider)

      enable(config=config, run_context=ctx, input_model=_In())
      enable(config=config, run_context=ctx, input_model=_In())

      # Same context object → only registered once.
      assert len(ctx.on_open) == 1
      assert len(ctx.on_close) == 1
      provider.shutdown()


  def test_enable_attaches_separate_hooks_for_distinct_contexts_with_same_run_id(
      fake_mlflow, tmp_path: Path
  ) -> None:
      """Idempotency keys on RunContext object identity (via WeakSet), not run_id.
      Two distinct RunContext instances with the same run_id each get their own
      hooks."""
      provider_a = TracerProvider()
      provider_b = TracerProvider()

      config = TelemetryConfig(
          otlp_endpoint="http://localhost:5000/v1/traces",
          otlp_headers={},
          service_name="archipelago-test",
          run_definition=RunDefinition(
              name=lambda inp: "n",
              params=lambda inp: {},
              tags={},
              metrics=lambda _out, _s: {},
          ),
      )
      ctx_a = _ctx(tmp_path, run_id="shared", provider=provider_a)
      ctx_b = _ctx(tmp_path, run_id="shared", provider=provider_b)

      enable(config=config, run_context=ctx_a, input_model=_In())
      enable(config=config, run_context=ctx_b, input_model=_In())

      assert len(ctx_a.on_open) == 1
      assert len(ctx_b.on_open) == 1
      provider_a.shutdown()
      provider_b.shutdown()


  def test_enable_raises_when_run_context_has_no_telemetry_provider(
      fake_mlflow, tmp_path: Path
  ) -> None:
      """Without a per-run TracerProvider on RunContext, enable() must fail
      loudly. This catches the ordering bug where a product calls enable() at
      startup before run_primitive_plan has run."""
      config = TelemetryConfig(
          otlp_endpoint="http://localhost:5000/v1/traces",
          otlp_headers={},
          service_name="archipelago-test",
      )
      ctx = _ctx(tmp_path, run_id="r-no-prov", provider=None)
      with pytest.raises(RuntimeError, match="telemetry_provider"):
          enable(config=config, run_context=ctx, input_model=_In())
  ```

- [ ] **Step 2: Run the failing test.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/mlflow_adapter/test_enable.py
  ```
  Expected: FAIL with `ImportError: cannot import name 'enable' from 'agent_foundry.mlflow_adapter'`.

- [ ] **Step 3: Implement `enable` — extends D1's skeleton, preserves the `extras` import path.**

  Edit `src/agent_foundry/mlflow_adapter/__init__.py`. The skeleton from D1 already imports the guard from `extras.py`; keep that import. Add the public `enable()` API and idempotency tracking on top:

  ```python
  """MLflow adapter for Agent Foundry telemetry.

  Provides:
    - ``MLFLOW_TRANSLATIONS``: attribute-translation table products plug into
      ``TelemetryConfig.attribute_translations`` to mirror AF span attributes
      under MLflow names. Translation happens at emit time, not as a
      SpanProcessor.
    - ``enable(config, run_context, input_model)``: attaches MLflow Run
      start/end hooks to ``run_context.on_open`` / ``on_close``.

  Optional install — requires the ``[mlflow]`` extra:

      pip install agent-foundry[mlflow]
  """

  from __future__ import annotations

  import threading
  import weakref

  from pydantic import BaseModel

  # Import-guard (raises actionable ImportError if mlflow isn't installed).
  # Kept from D1's skeleton — extras.py owns the import-guard logic so other
  # adapter modules can import from it uniformly.
  from agent_foundry.mlflow_adapter import extras  # noqa: F401
  from agent_foundry.mlflow_adapter.run_lifecycle import attach_run_hooks
  from agent_foundry.mlflow_adapter.translation import MLFLOW_TRANSLATIONS
  from agent_foundry.orchestration.run_context import RunContext
  from agent_foundry.telemetry.config import TelemetryConfig

  # Idempotency tracking, keyed on RunContext object identity (via id()).
  #
  # We deliberately do NOT use ``weakref.WeakSet`` here: WeakSet uses
  # ``__hash__`` / ``__eq__`` for membership, and Pydantic frozen models hash
  # by field values — two distinct RunContext instances with all the same
  # field values would collide. Object identity is what we want.
  #
  # Stale ``id()`` entries are pruned when the RunContext is garbage-collected
  # via ``weakref.finalize``, so the set never accumulates stale state in
  # long-running processes.
  _ENABLED_CONTEXT_IDS: set[int] = set()
  _ENABLED_CONTEXTS_LOCK = threading.Lock()


  def reset_for_testing() -> None:
      """Clear the idempotency-tracking set. Tests call this in fixtures so
      contexts created in earlier tests don't suppress registration in later
      tests. Not part of the production surface — finalize handles real
      RunContext lifetimes automatically.
      """
      with _ENABLED_CONTEXTS_LOCK:
          _ENABLED_CONTEXT_IDS.clear()


  def _unregister(ctx_id: int) -> None:
      """Remove a context id from the enabled set. Called by weakref.finalize
      when the RunContext is garbage-collected, preventing id() reuse hazards.
      """
      with _ENABLED_CONTEXTS_LOCK:
          _ENABLED_CONTEXT_IDS.discard(ctx_id)


  def enable(
      *,
      config: TelemetryConfig,
      run_context: RunContext,
      input_model: BaseModel,
  ) -> None:
      """Wire the MLflow adapter into a per-run telemetry pipeline.

      **Ordering constraint**: must be called from a ``run_context.on_open``
      hook (or any callsite that runs after ``run_primitive_plan`` has built a
      ``TracerProvider`` and anchored it on ``run_context.telemetry_provider``).
      Calling at process startup, before ``run_primitive_plan``, raises
      ``RuntimeError`` because no per-run provider exists yet.

      Idempotent within a process: registering the same ``run_context`` twice
      is a no-op. Different ``run_context`` instances always get their own
      hooks, even if they share a ``run_id``. Thread-safe: concurrent calls
      on the same context are serialised so that exactly one set of hooks is
      attached.

      Note: this function does NOT register a SpanProcessor. Attribute
      translation happens at emit time via
      ``TelemetryConfig.attribute_translations`` (set by the product to
      ``MLFLOW_TRANSLATIONS`` exported from this module). The MLflow Run
      lifecycle hooks are the only side effect.
      """
      provider = run_context.telemetry_provider
      if provider is None:
          raise RuntimeError(
              "agent_foundry.mlflow_adapter.enable() requires "
              "run_context.telemetry_provider to be set. "
              "Pass telemetry=config to run_primitive_plan first."
          )

      ctx_id = id(run_context)
      with _ENABLED_CONTEXTS_LOCK:
          if ctx_id in _ENABLED_CONTEXT_IDS:
              return  # already enabled for this run

          if config.run_definition is not None:
              attach_run_hooks(
                  run_context=run_context,
                  run_definition=config.run_definition,
                  redaction=config.redaction,
                  input_model=input_model,
              )

          _ENABLED_CONTEXT_IDS.add(ctx_id)
          weakref.finalize(run_context, _unregister, ctx_id)


  __all__ = ["enable", "reset_for_testing", "MLFLOW_TRANSLATIONS"]
  ```

- [ ] **Step 4: Run the tests.**

  Run:
  ```bash
  pdm test-unit tests/agent_foundry/mlflow_adapter/test_enable.py
  ```
  Expected: 3 PASSED.

- [ ] **Step 5: Run the full test suite.**

  Run:
  ```bash
  pdm test-all
  ```
  Expected: PASS.

- [ ] **Step 6: Lint and typecheck.**

  Run:
  ```bash
  pdm lint
  pdm typecheck
  ```
  Expected: both PASS.

- [ ] **Step 7: Commit.**

  ```bash
  git add src/agent_foundry/mlflow_adapter/__init__.py \
          tests/agent_foundry/mlflow_adapter/test_enable.py
  git commit -m "feat(mlflow): wire adapter into telemetry pipeline via enable()"
  ```

---

## Phase E — Verification Demo

### Task E1: Local MLflow `docker-compose`

**Files:**
- Create: `examples/mlflow_demo/docker-compose.yaml`
- Create: `examples/mlflow_demo/README.md`

**Dependencies:** None (independent of all other tasks).

This task is purely structural — no production code is added, so TDD steps simplify.

- [ ] **Step 1: Create the compose file.**

  Create `examples/mlflow_demo/docker-compose.yaml`:

  ```yaml
  services:
    mlflow:
      image: ghcr.io/mlflow/mlflow:v3.7.0
      ports:
        - "5000:5000"
      command:
        - mlflow
        - server
        - --host=0.0.0.0
        - --port=5000
        - --backend-store-uri=sqlite:////mlflow/mlflow.db
        - --default-artifact-root=/mlflow/artifacts
      volumes:
        - mlflow_data:/mlflow

  volumes:
    mlflow_data:
  ```

- [ ] **Step 2: Create the README.**

  Create `examples/mlflow_demo/README.md`:

  ```markdown
  # MLflow Tracing Demo

  Local MLflow server for the AF tracing verification demo.

  ## Requirements

  - Docker
  - Docker Compose v2

  ## Bring it up

  ```bash
  cd examples/mlflow_demo
  docker compose up -d
  ```

  Server: http://localhost:5000

  Backend: SQLite (required for OTLP trace ingest — file-store backend is unsupported).

  ## Create an experiment

  Open http://localhost:5000 and click **Create Experiment**. Name it
  `archipelago-demo` (or anything). Note the numeric **Experiment ID**.

  ## Run the example

  See `main.py` for the end-to-end example product. It reads the experiment ID
  from `AF_MLFLOW_EXPERIMENT_ID`:

  ```bash
  export AF_MLFLOW_EXPERIMENT_ID=<id>
  pdm run python examples/mlflow_demo/main.py
  ```

  ## Tear it down

  ```bash
  docker compose down
  ```

  Volumes persist data across restarts. Add `-v` to wipe them:

  ```bash
  docker compose down -v
  ```
  ```

- [ ] **Step 3: Verify the compose file is valid.**

  Run:
  ```bash
  docker compose -f examples/mlflow_demo/docker-compose.yaml config
  ```
  Expected: prints the resolved compose config without errors.

- [ ] **Step 4: Verify the server boots.**

  Run:
  ```bash
  docker compose -f examples/mlflow_demo/docker-compose.yaml up -d
  curl -sf http://localhost:5000 > /dev/null && echo "OK"
  ```
  Expected: prints `OK`. (May need to wait a few seconds after `up -d` for the server to bind.)

- [ ] **Step 5: Tear down.**

  Run:
  ```bash
  docker compose -f examples/mlflow_demo/docker-compose.yaml down
  ```
  Expected: containers stop cleanly.

- [ ] **Step 6: Commit.**

  ```bash
  git add examples/mlflow_demo/docker-compose.yaml \
          examples/mlflow_demo/README.md
  git commit -m "docs(mlflow): add local docker-compose for verification demo"
  ```

---

### Task E2: Example product script

**Files:**
- Create: `examples/mlflow_demo/main.py`

**Dependencies:** Requires Task D4.

- [ ] **Step 1: Create the example.**

  Create `examples/mlflow_demo/main.py`:

  ```python
  """End-to-end verification demo for MLflow tracing integration.

  Wires a tiny AgentAction plan with a deterministic fake executor, configures
  telemetry pointing at a local MLflow server, runs the plan, and exits.

  Expects MLflow at http://localhost:5000 (see docker-compose.yaml). Reads
  the experiment id from the env var ``AF_MLFLOW_EXPERIMENT_ID``.
  """

  from __future__ import annotations

  import asyncio
  import os
  from pathlib import Path

  from pydantic import BaseModel

  from agent_foundry.mlflow_adapter import (
      MLFLOW_TRANSLATIONS,
      enable as enable_mlflow_adapter,
  )
  from agent_foundry.orchestration.runner import run_primitive_plan
  from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy
  from agent_foundry.primitives.plan import PrimitivePlan
  from agent_foundry.telemetry import RunDefinition, TelemetryConfig


  class TicketInput(BaseModel):
      ticket_id: str
      kind: str


  class TicketOutput(BaseModel):
      success: bool
      summary: str


  def fake_executor(*, primitive: AgentAction, prompt: str, instructions: str, run_ctx) -> TicketOutput:
      return TicketOutput(success=True, summary=f"handled: {prompt[:60]}")


  def build_plan() -> PrimitivePlan:
      action = AgentAction[TicketInput, TicketOutput](
          name="reviewer",
          prompt_builder=lambda inp: f"review ticket {inp.ticket_id} ({inp.kind})",
          instructions_provider=lambda _: "be terse, return TicketOutput",
          executor=fake_executor,
          reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
      )
      return PrimitivePlan(root=action)


  def build_telemetry() -> TelemetryConfig:
      experiment_id = os.environ.get("AF_MLFLOW_EXPERIMENT_ID", "0")
      return TelemetryConfig(
          otlp_endpoint=os.environ.get(
              "AF_OTLP_ENDPOINT", "http://localhost:5000/v1/traces"
          ),
          otlp_headers={"x-mlflow-experiment-id": experiment_id},
          service_name="archipelago-demo",
          attribute_translations=MLFLOW_TRANSLATIONS,
          run_definition=RunDefinition(
              name=lambda inp: f"ticket-{inp.ticket_id}",
              params=lambda inp: {"ticket_id": inp.ticket_id, "kind": inp.kind},
              tags={"product": "archipelago", "env": "demo"},
              metrics=lambda out, stats: (
                  {
                      "duration_ms": stats.duration_ms,
                      "success": float(out.success),
                  }
                  if out is not None
                  else {"duration_ms": stats.duration_ms}
              ),
          ),
      )


  async def main(run_id: str | None = None) -> TicketOutput:
      """Run the demo plan once and return the result.

      Accepts an optional ``run_id`` so the live smoke test can call ``main``
      multiple times with distinct IDs (each run bootstraps its own
      ``run_dir`` under ``artifacts_dir``, and ``bootstrap_run_artifacts``
      raises FileExistsError on collision).
      """
      import uuid

      resolved_run_id = run_id or f"demo-{uuid.uuid4().hex[:8]}"
      artifacts_dir = Path.cwd() / ".tmp" / "mlflow-demo"
      artifacts_dir.mkdir(parents=True, exist_ok=True)

      plan = build_plan()
      config = build_telemetry()
      input_model = TicketInput(ticket_id="42", kind="feature")

      def attach_adapter(ctx) -> None:
          enable_mlflow_adapter(config=config, run_context=ctx, input_model=input_model)

      result = await run_primitive_plan(
          plan,
          initial_state=input_model,
          artifacts_dir=artifacts_dir,
          workspace_volume="archipelago-demo",
          base_image_tag="agent-worker:latest",
          responder_provider=lambda _id: lambda *a, **k: None,
          run_id=resolved_run_id,
          telemetry=config,
          on_open=[attach_adapter],
      )

      print(f"Plan completed (run_id={resolved_run_id}). Result: {result!r}")
      print("Open http://localhost:5000 and look for run 'ticket-42'.")
      return result


  if __name__ == "__main__":
      asyncio.run(main())
  ```

- [ ] **Step 2: Run the example against a live MLflow.**

  Run:
  ```bash
  docker compose -f examples/mlflow_demo/docker-compose.yaml up -d
  # Open http://localhost:5000, create an experiment, copy the numeric ID:
  export AF_MLFLOW_EXPERIMENT_ID=1
  pdm run python examples/mlflow_demo/main.py
  ```
  Expected: script prints "Plan completed" and a "look for run 'ticket-42'" line. In the MLflow UI, the experiment shows a run named `ticket-42` with params, tags, metrics, and a trace containing one AgentAction span carrying both `agent_foundry.*` and `mlflow.*` attributes plus `gen_ai.operation.name = "chat"`.

- [ ] **Step 3: Tear down the local MLflow.**

  Run:
  ```bash
  docker compose -f examples/mlflow_demo/docker-compose.yaml down
  ```

- [ ] **Step 4: Commit.**

  ```bash
  git add examples/mlflow_demo/main.py
  git commit -m "docs(mlflow): add end-to-end verification demo example"
  ```

---

### Task E3: Live smoke test

**Files:**
- Create: `examples/__init__.py`
- Create: `examples/mlflow_demo/__init__.py`
- Modify: `pyproject.toml` (add `examples` to `pythonpath`)
- Create: `tests/agent_foundry/mlflow_adapter/test_verification_demo.py`

**Dependencies:** Requires Task E2.

The smoke test imports `from examples.mlflow_demo.main import main`. For that import to work, `examples/` must be a Python package (needs an `__init__.py`) and the package root must be on Python's import path. `pyproject.toml`'s `[tool.pytest.ini_options] pythonpath = ["src"]` covers `src/` but not `examples/`, so we extend it to `["src", "."]` (pytest treats `.` as the repo root) — that way `examples.mlflow_demo.main` is importable from the smoke test.

- [ ] **Step 1: Make `examples` importable.**

  Create `examples/__init__.py` (empty file):

  ```python
  ```

  Create `examples/mlflow_demo/__init__.py` (empty file):

  ```python
  ```

  Edit `pyproject.toml` to extend `pythonpath`:

  ```toml
  [tool.pytest.ini_options]
  testpaths = ["tests"]
  pythonpath = ["src", "."]
  addopts = "-m 'not benchmark' -n 8"
  asyncio_mode = "strict"
  ```

  Verify pytest's path resolution via collection (the PDM script env's `PYTHONPATH=src` does not include `.`, so a `python -c` check would mislead — pytest's ini config is what matters):
  ```bash
  pdm test-unit --collect-only -k verification_demo
  ```
  Expected: pytest collects `test_verification_demo.py` without `ImportError`. Tests are reported as collected (and would skip at runtime if `AF_LIVE_MLFLOW=1` isn't set — that's the expected default behavior).

- [ ] **Step 2: Write the live smoke test.**

  Create `tests/agent_foundry/mlflow_adapter/test_verification_demo.py`:

  ```python
  """Live smoke test: runs the demo against a real local MLflow.

  Skipped unless ``AF_LIVE_MLFLOW=1`` is set in the environment. Use:

      docker compose -f examples/mlflow_demo/docker-compose.yaml up -d
      export AF_LIVE_MLFLOW=1
      export AF_MLFLOW_EXPERIMENT_ID=<id>
      pdm test-all -k verification_demo
  """

  from __future__ import annotations

  import asyncio
  import os

  import pytest


  pytestmark = pytest.mark.skipif(
      os.environ.get("AF_LIVE_MLFLOW") != "1",
      reason="Live MLflow required (set AF_LIVE_MLFLOW=1)",
  )


  @pytest.mark.integration
  def test_verification_demo_run_appears_in_mlflow() -> None:
      import uuid

      from mlflow.tracking import MlflowClient

      from examples.mlflow_demo.main import main

      run_id = f"smoke-run-{uuid.uuid4().hex[:8]}"
      asyncio.run(main(run_id=run_id))

      experiment_id = os.environ["AF_MLFLOW_EXPERIMENT_ID"]
      client = MlflowClient(tracking_uri="http://localhost:5000")
      runs = client.search_runs(
          experiment_ids=[experiment_id],
          filter_string="tags.mlflow.runName = 'ticket-42'",
          max_results=10,
      )

      assert len(runs) >= 1, "Expected at least one run named ticket-42"
      run = runs[0]
      assert run.data.params["ticket_id"] == "42"
      assert run.data.params["kind"] == "feature"
      assert run.data.tags.get("product") == "archipelago"
      assert "duration_ms" in run.data.metrics


  @pytest.mark.integration
  def test_verification_demo_trace_carries_both_namespaces() -> None:
      import uuid

      import mlflow

      from examples.mlflow_demo.main import main

      run_id = f"smoke-trace-{uuid.uuid4().hex[:8]}"
      asyncio.run(main(run_id=run_id))

      experiment_id = os.environ["AF_MLFLOW_EXPERIMENT_ID"]
      traces = mlflow.search_traces(
          experiment_ids=[experiment_id], max_results=10
      )
      assert len(traces) >= 1, "Expected at least one trace"
      # MLflow's trace API exposes spans on the trace; verify the AgentAction
      # span carries both AF and MLflow namespaces.
      spans = traces.iloc[0].spans  # pandas DataFrame layout
      assert len(spans) >= 1
      span = spans[0]
      attrs = span.attributes
      assert "agent_foundry.input" in attrs
      assert "mlflow.spanInputs" in attrs
      assert attrs.get("gen_ai.operation.name") == "chat"
  ```

- [ ] **Step 3: Verify the test is skipped by default.**

  Run:
  ```bash
  pdm test-all -k verification_demo
  ```
  Expected: tests SKIPPED with reason "Live MLflow required (set AF_LIVE_MLFLOW=1)".

- [ ] **Step 4: Run the test against a live MLflow.**

  Run (with the local MLflow already up from E1):
  ```bash
  export AF_LIVE_MLFLOW=1
  export AF_MLFLOW_EXPERIMENT_ID=<the experiment id from E1>
  pdm test-integration -k verification_demo
  ```
  Expected: 2 PASSED.

- [ ] **Step 5: Commit.**

  ```bash
  git add examples/__init__.py \
          examples/mlflow_demo/__init__.py \
          pyproject.toml \
          tests/agent_foundry/mlflow_adapter/test_verification_demo.py
  git commit -m "test(mlflow): add live verification-demo smoke test"
  ```

---

## Self-Review

This is the 5-point checklist run after writing the plan, before requesting approval.

**1. Spec coverage.** Walking the design doc section by section:

- "Architecture" — A1, A4, B1–B6, D1–D4 cover the two-module split. ✅
- "Run boundary" — A1 (rename), A3 (lifecycle hooks), B6 (telemetry stash on RunContext). ✅
- "RunDefinition" — B1 (model), D3 (consumed by lifecycle hooks). ✅
- "TelemetryConfig" — B1 (model), B6 (threading). ✅
- "Attribute namespace contract" — B2 (constants), B5 (compiler emits), D2 (translation). ✅
- "Span emission points (this stage)" — B5 covers AgentAction. ✅
- "Redaction" — B4 wires it through; C1 covers full edge cases. ✅
- "Run lifecycle (MLflow adapter)" — D3, D4. ✅
- "File layout" — File Structure table at top of plan matches. ✅
- "Dependencies" — A4. ✅
- "Verification Demo" — E1, E2, E3. ✅
- "Open items" (concurrency under asyncio, OTLP-ingest assessments compatibility) — concurrency surfaces during E3 if it bites; assessments compatibility is explicitly out of scope. ✅
- "Translation is additive, not destructive" — D2 has explicit tests for the additive contract. ✅

No gaps.

**2. Placeholder scan.** Searching for "TBD", "TODO", "implement later", "appropriate", "similar to", "and so on", "etc.":

- B5's helper references the existing `_compile_agent_action` structure by description rather than copying the unchanged surrounding code. The engineer is editing the same file so the existing pattern is in front of them. The task does provide complete, correct code blocks for the parts that change (the new `_validate_typed`, the rewritten `node_fn_async` and `node_fn_sync`, the executor call with all four kwargs, the `emit_span` wrap, the `redaction` lookup via `getattr` so it survives B5-before-B6 ordering).
- A3's `summary.py` update step (Step 8b) sketches the renderer logic with `...` for surrounding code rather than copying the full file. The engineer is editing the same file so the existing pattern is in front of them; the change is mechanical (add one `elif` branch + one local boolean).
- A3's `test_summary.py` test sketch uses `...` placeholders for fixture body. The engineer is told to follow the existing test file's idiom; the assertion targets are explicit (`(incomplete)` not in output, "failed" in header).
- The plan's first-pass review identified four blocking issues in B5 (executor signature dropped two kwargs; `_validate_and_return` returned a dict that was passed to `set_output`; `await` on a sync function; example/test stubs replicated the bad signature). All are fixed in the current revision.
- The plan's second-pass review identified one blocker (E3 `FileExistsError` from duplicate run_id), six majors (`summary.py` not handling `RUN_FAILED`, sealed-set test failure, process-global tracer-provider, on_close-vs-render_summary ordering, undefended `metrics` orphaning runs, D4/D1 extras inconsistency), and several minors. All are fixed in the current revision.
- The plan's third-pass review identified additional architectural issues: `MLflowAttributeProcessor`'s post-end mutation is a no-op under `BatchSpanProcessor` (OTel's `_check_span_ended` rule); `WeakSet` over Pydantic frozen models hashes by field equality (collisions on equal contexts); `enable()` had a check-and-add race; `build_tracer_provider` failure leaked `run_dir`; `_trace.get_current_span()` doesn't propagate to worker threads; `log_artifact` failures silently produced FINISHED runs. All are fixed in the current revision: translation moved to emit-time via `TelemetryConfig.attribute_translations` + `MLFLOW_TRANSLATIONS` constant; idempotency keyed on `id()` with `weakref.finalize` cleanup and `threading.Lock`; explicit `shutil.rmtree` cleanup on provider build failure; `handle.set_operation_name(...)` used instead of `_trace.get_current_span()`; `log_artifact` failure escalates status to FAILED.

No other placeholders.

**3. Type consistency.** Cross-checking names:

- `RunContext` — defined in A1, used in A3, B5, B6, D3, D4, E2. ✅
- `TelemetryConfig` — defined in B1, used in B6, D4, E2. ✅
- `RunDefinition` — defined in B1, used in D3, D4, E2. ✅
- `RunStats` — defined in B1, used in D3 (constructed and passed to the metrics callable). ✅
- `RedactionPolicy` — defined in B1, used in B4, B6, C1, D3. ✅
- `ArtifactSpec` — defined in B1, used in D3. ✅
- `SpanHandle` — defined in B4, used implicitly in B5. ✅
- `MLFLOW_TRANSLATIONS` — defined in D2, used in D4 (re-export) and E2 (example product). ✅
- `attach_run_hooks` — defined in D3, used in D4. ✅
- `enable` — defined in D4, used in E2. ✅
- `emit_span` — defined in B4, used in B5. ✅
- `build_tracer_provider` — defined in B3, used in B6. ✅

Constants:
- `attributes.AF_INPUT` etc. — defined in B2, used in B4, B5, C1, D2, E3. ✅

**4. Dependency ordering.**

- A1, A2, A4 are independent (parallel-eligible).
- A3 depends on A1.
- B1 and B2 are independent of each other and depend on A4.
- B3 depends on B1.
- B4 depends on B1 + B2.
- B5 depends on A1 + B4.
- B6 depends on A3 + B3 + B5.
- C1 depends on B4 only (loosened from earlier draft — C1's tests don't go through the runner or compiler, so B6 is not a prerequisite; C1 can run in parallel with B6 once B4 is done).
- D1 depends on A4.
- D2 depends on B2 + D1.
- D3 depends on A3 + B1 + D1.
- D4 depends on D1 + D2 + D3 + B6.
- E1 is independent.
- E2 depends on D4.
- E3 depends on E2.

No cycles. Phase A → B → C/D → E ordering is sound. Within phases, parallelism is available where flagged.

**5. Command accuracy.**

- `pdm test-all`, `pdm test-unit`, `pdm test-integration`, `pdm lint`, `pdm typecheck` — confirmed against `pyproject.toml` `[tool.pdm.scripts]`. ✅
- `pdm add <package>` — standard PDM. ✅
- `docker compose -f <path> up -d` / `down` / `config` — standard Docker Compose v2. ✅
- `git add <files>` and `git commit -m "<message>"` — standard. Commit subjects use `type(scope): message` matching `jig.config.md` `convention: conventional`. ✅
- `pytest -k <pattern>` and `@pytest.mark.asyncio` / `@pytest.mark.integration` — match repo's `asyncio_mode = "strict"` and `markers` in `pyproject.toml`. ✅

No issues.

---

## Plan Review Swarm

The skill prescribes invoking `jig:review` with `mode: plan` after self-review and before requesting approval. The review swarm hasn't been invoked yet — that's the next step the user needs to confirm before we move to execution. The swarm dispatches plan-stage specialists in parallel and a plan-logic reviewer (Opus) for deep correctness analysis.

**Want me to dispatch the review swarm now?** It runs against this plan document and the design doc, and produces a scored findings report. After that, you decide whether to address findings before approving and moving to execution.

---

## Execution Handoff

Once the plan is approved (and any review-swarm findings addressed), two execution options:

1. **Team-Driven (parallel)** — `jig:team-dev`. Spawns implementer teammates in split panes; staggered review pipeline. Good fit for this plan because Phase A and Phase B have independent tasks (A1+A2+A4 parallel; B1+B2 parallel; D1 can start as soon as A4 lands while B work proceeds). `jig.config.md` has `parallel-threshold: 3` and `default-strategy: team-dev`, matching this profile.

2. **Subagent-Driven (sequential)** — `jig:sdd`. Fresh subagent per task, two-stage review after each. Use if you'd rather review every task individually and the parallelism gain is not worth the orchestration overhead.

Default recommendation per `jig.config.md`: **team-dev**. But the call is yours.
