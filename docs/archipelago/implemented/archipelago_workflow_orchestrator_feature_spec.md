# Feature Specification: Archipelago Workflow Orchestrator

## Objective

Implement an end-to-end Archipelago pipeline that chains four agent stages -- strategy, architecture, spec, dev/test -- on the existing agent-foundry platform. The pipeline replaces manual inter-stage routing with a plan-compiled, schema-enforced, observable workflow that supports breakpoint gates and checkpoint/resume.

### Success Criteria

1. A single `GraphWiringPlan` describes the full Archipelago pipeline (4 stages + breakpoint gates) and passes all 7 existing validator checks.
2. Each pipeline stage has a registered `CapabilitySpec` with strict JSON Schema I/O contracts enforced at runtime.
3. Real LLM-backed handlers (langchain-anthropic) produce typed Pydantic artifacts at each stage.
4. End-to-end execution from `ProductBrief` input to `TestResults` output completes with full tracing spans.
5. Checkpoint/resume allows halting after any breakpoint and resuming without re-executing completed stages.
6. All existing tests (29 files) remain green throughout; no regressions.

---

## Constraints

### Technical
- Must use the existing `CapabilityRegistry`, `GraphWiringPlan`, `compile_plan()`, `ExecutionTracer`, and eval gate infrastructure without forking or duplicating them.
- Pydantic v2 models for all data structures.
- JSON Schema (Draft 7) for capability I/O contracts, validated by `jsonschema` at runtime via `execute_capability()`.
- LangGraph `StateGraph` as the execution engine; LangGraph's built-in checkpointing for persistence.
- `langchain-anthropic` for LLM calls (already a dependency).
- Python 3.13 (per `pyproject.toml`), PDM for package management.

### Scope
- **In scope**: The 4-stage linear pipeline (strategy -> architecture -> spec -> dev/test) with breakpoint gates, real LLM handlers, tracing, and checkpoint/resume.
- **Out of scope**: Loops (spec-revise loop, implement-test-fix loop), Docker-based Claude Code worker, DSPy integration, deploy/release stages, advanced retrieval-planner sophistication. These are deferred to future work.

### Quality
- TDD throughout: tests written before implementation, red-green-refactor.
- Each PR independently mergeable; system stays in a working state after each merge.
- Each commit atomic and focused on a single concern.
- Test naming follows Given/When/Then convention where practical.

### Time
- Phase 1 (state models + capability specs) is the foundation; all subsequent phases depend on it.
- Phases 2-4 can begin only after Phase 1 is merged.
- Phase 3 (LLM handlers) can begin in parallel with Phase 4 (checkpoint/resume) once Phase 2 is merged.

---

## Acceptance Criteria

### Phase 1: State Models & Capability Specs

1. **Given** the `archipelago.models` module exists, **when** a `ProductBrief` is instantiated with valid fields, **then** it validates successfully and round-trips through `model_dump_json()` / `model_validate_json()` with no field loss.
2. **Given** the `archipelago.models` module exists, **when** a `FeatureArchitecture`, `FeatureSpec`, `TestPlan`, `CodePatch`, or `TestResults` is instantiated with valid fields, **then** each validates and round-trips identically.
3. **Given** any artifact model, **when** instantiated with missing required fields, **then** a Pydantic `ValidationError` is raised listing the missing fields.
4. **Given** a YAML capability spec file for `strategy.generate_product_brief`, **when** loaded via `load_capability_spec()`, **then** it returns a valid `CapabilitySpec` with `inputs_schema` and `outputs_schema` that match the `ProductBrief` model's JSON Schema.
5. **Given** all 4 Archipelago capability YAML specs exist in `src/archipelago/capabilities/`, **when** `CapabilityRegistry.from_directory()` is called on that directory, **then** the registry contains all 4 new capabilities alongside the existing 8, totaling 12.
6. **Given** any Archipelago capability spec, **when** its `outputs_schema` is used to validate the corresponding Pydantic model's `.model_dump()`, **then** JSON Schema validation passes.
7. **Given** the Archipelago capability specs, **when** searched by tag `"archipelago"`, **then** all 4 and only those 4 are returned.

### Phase 2: Pipeline Plan & Planner Extension

8. **Given** a `GraphWiringPlan` for goal `"archipelago-pipeline"` with 4 stage nodes, 1 breakpoint gate node, and edges chaining them linearly, **when** parsed from JSON, **then** all fields are present and the plan round-trips.
9. **Given** the archipelago pipeline plan and a registry with all 12 capabilities, **when** `validate_plan()` is called, **then** no validation errors are raised (all 7 checks pass).
10. **Given** a `WiringPlanner` initialized with the full registry, **when** `planner.plan("archipelago-pipeline")` is called, **then** it returns a valid `GraphWiringPlan` with the correct 5 nodes and 4 edges.
11. **Given** the archipelago pipeline plan, **when** the breakpoints list is inspected, **then** it contains `"spec_approval_gate"` (the gate between spec and dev/test stages).
12. **Given** the archipelago pipeline plan, **when** `capability_versions` is inspected, **then** every node's capability has a version entry.

### Phase 3: LLM-Backed Handlers

13. **Given** a `strategy_handler` function and a state dict with a `product_brief_input` field, **when** the handler is called, **then** it returns a state dict containing a `product_brief` field whose value validates against the `ProductBrief` JSON Schema.
14. **Given** an `architecture_handler` function and a state dict containing a valid `product_brief`, **when** the handler is called, **then** it returns a state dict containing a `feature_architecture` field that validates against `FeatureArchitecture` JSON Schema.
15. **Given** a `spec_handler` function and a state dict containing a valid `feature_architecture`, **when** the handler is called, **then** it returns a state dict containing both `feature_spec` and `test_plan` fields that validate against their respective JSON Schemas.
16. **Given** a `dev_test_handler` function and a state dict containing a valid `feature_spec` and `test_plan`, **when** the handler is called, **then** it returns a state dict containing `code_patch` and `test_results` fields that validate.
17. **Given** all 4 handlers wired into a `handler_registry` and compiled via `compile_plan()`, **when** the graph is invoked with a valid initial state, **then** the final state contains all 6 artifact fields populated and valid.
18. **Given** an end-to-end run with an `ExecutionTracer`, **when** tracing spans are exported, **then** there is one span per node (5 total), each with status `"ok"` and non-zero duration.

### Phase 4: Checkpoint/Resume

19. **Given** a `GraphWiringPlan` with `persistence` set to `{"backend": "memory", "thread_id": "test-1"}`, **when** `compile_plan()` is called, **then** the compiled graph supports checkpointing (has a `checkpointer` attribute or equivalent).
20. **Given** a compiled graph with checkpointing enabled and a breakpoint at `spec_approval_gate`, **when** the graph is invoked, **then** execution pauses at the breakpoint and the checkpoint contains the state up to (but not including) the gate node.
21. **Given** a paused execution with a checkpoint, **when** the graph is resumed with an approval signal, **then** execution continues from the gate node through `dev_test` to completion without re-executing prior nodes.
22. **Given** a checkpoint persisted to the memory backend, **when** a new graph is compiled from the same plan and thread_id, **then** the checkpoint can be loaded and execution resumed.

---

## PR/Commit Slices

### PR 1: Archipelago Artifact Models (Phase 1a)

**Description**: Define the 6 canonical Pydantic models that represent the typed artifacts flowing through the pipeline. These models are the foundation for I/O schema enforcement.

**Acceptance Criteria Addressed**: #1, #2, #3

**Complexity**: S

**Dependencies**: None

**Files created**:
- `src/agent_foundry/archipelago/__init__.py`
- `src/agent_foundry/archipelago/models.py`
- `tests/test_archipelago_models.py`

**Commits**:

1. **Add ProductBrief and FeatureArchitecture Pydantic models**
   - Create `src/agent_foundry/archipelago/__init__.py` (empty package marker).
   - Create `src/agent_foundry/archipelago/models.py` with `ProductBrief` and `FeatureArchitecture` models.
   - `ProductBrief` fields: `name: str`, `problem_statement: str`, `target_personas: list[str]`, `success_metrics: list[str]`, `constraints: list[str]` (optional, default `[]`).
   - `FeatureArchitecture` fields: `feature_name: str`, `components: list[str]`, `data_flow: str`, `technology_choices: list[str]`, `risks: list[str]` (optional, default `[]`).
   - Create `tests/test_archipelago_models.py` with tests:
     - `TestProductBrief::test_given_valid_fields_when_instantiated_then_validates`
     - `TestProductBrief::test_given_valid_instance_when_json_round_tripped_then_no_field_loss`
     - `TestProductBrief::test_given_missing_required_field_when_instantiated_then_raises_validation_error`
     - `TestFeatureArchitecture::test_given_valid_fields_when_instantiated_then_validates`
     - `TestFeatureArchitecture::test_given_valid_instance_when_json_round_tripped_then_no_field_loss`
     - `TestFeatureArchitecture::test_given_missing_required_field_when_instantiated_then_raises_validation_error`

2. **Add FeatureSpec, TestPlan, CodePatch, and TestResults models**
   - Add to `models.py`:
     - `FeatureSpec` fields: `title: str`, `objective: str`, `acceptance_criteria: list[str]`, `pr_slices: list[dict[str, Any]]`.
     - `TestPlan` fields: `feature_name: str`, `test_cases: list[dict[str, Any]]`, `coverage_targets: list[str]`.
     - `CodePatch` fields: `feature_name: str`, `files_changed: list[str]`, `diff_summary: str`, `branch_name: str`.
     - `TestResults` fields: `feature_name: str`, `tests_passed: int`, `tests_failed: int`, `test_output: str`, `all_green: bool`.
   - Add tests to `tests/test_archipelago_models.py`:
     - `TestFeatureSpec::test_given_valid_fields_when_instantiated_then_validates`
     - `TestFeatureSpec::test_given_valid_instance_when_json_round_tripped_then_no_field_loss`
     - `TestFeatureSpec::test_given_missing_required_field_when_instantiated_then_raises_validation_error`
     - `TestTestPlan::test_given_valid_fields_when_instantiated_then_validates`
     - `TestTestPlan::test_given_valid_instance_when_json_round_tripped_then_no_field_loss`
     - `TestCodePatch::test_given_valid_fields_when_instantiated_then_validates`
     - `TestCodePatch::test_given_valid_instance_when_json_round_tripped_then_no_field_loss`
     - `TestTestResults::test_given_valid_fields_when_instantiated_then_validates`
     - `TestTestResults::test_given_valid_instance_when_json_round_tripped_then_no_field_loss`
     - `TestTestResults::test_given_missing_required_field_when_instantiated_then_raises_validation_error`

---

### PR 2: Archipelago Capability Specs (Phase 1b)

**Description**: Create YAML capability spec files for the 4 pipeline stages and verify they load into the existing registry alongside the 8 existing capabilities.

**Acceptance Criteria Addressed**: #4, #5, #6, #7

**Complexity**: S

**Dependencies**: PR 1 (models must exist for schema reference)

**Files created**:
- `src/archipelago/capabilities/strategy_generate_product_brief.yaml`
- `src/archipelago/capabilities/architecture_generate_feature_arch.yaml`
- `src/archipelago/capabilities/spec_generate_feature_spec.yaml`
- `src/archipelago/capabilities/dev_implement_feature_tdd.yaml`
- `tests/test_archipelago_capability_specs.py`

**Commits**:

1. **Add strategy and architecture capability spec YAML files**
   - Create `src/archipelago/capabilities/strategy_generate_product_brief.yaml`:
     - `name: strategy_generate_product_brief`
     - `description: Generates a product brief from high-level input`
     - `version: "1.0.0"`
     - `implementation: {module: agent_foundry.archipelago.handlers, class_name: StrategyHandler}`
     - `inputs_schema`: JSON Schema for `{product_brief_input: string}` (required)
     - `outputs_schema`: JSON Schema matching `ProductBrief.model_json_schema()`
     - `tags: [archipelago, strategy, generation]`
     - `quality_controls: {timeout_seconds: 120, max_retries: 1}`
   - Create `src/archipelago/capabilities/architecture_generate_feature_arch.yaml` with analogous structure, inputs referencing `ProductBrief` schema, outputs referencing `FeatureArchitecture` schema.
   - Create `tests/test_archipelago_capability_specs.py` with tests:
     - `TestStrategySpec::test_given_yaml_file_when_loaded_then_returns_valid_capability_spec`
     - `TestStrategySpec::test_given_strategy_spec_when_outputs_schema_validates_model_dump_then_passes`
     - `TestArchitectureSpec::test_given_yaml_file_when_loaded_then_returns_valid_capability_spec`
     - `TestArchitectureSpec::test_given_architecture_spec_when_outputs_schema_validates_model_dump_then_passes`

2. **Add spec and dev/test capability spec YAML files**
   - Create `src/archipelago/capabilities/spec_generate_feature_spec.yaml`:
     - Inputs reference `FeatureArchitecture` schema.
     - Outputs reference both `FeatureSpec` and `TestPlan` schemas (combined object).
     - `tags: [archipelago, spec, generation]`
   - Create `src/archipelago/capabilities/dev_implement_feature_tdd.yaml`:
     - Inputs reference `FeatureSpec` and `TestPlan` schemas.
     - Outputs reference `CodePatch` and `TestResults` schemas (combined object).
     - `tags: [archipelago, dev, tdd, implementation]`
   - Add tests:
     - `TestSpecSpec::test_given_yaml_file_when_loaded_then_returns_valid_capability_spec`
     - `TestSpecSpec::test_given_spec_spec_when_outputs_schema_validates_model_dump_then_passes`
     - `TestDevSpec::test_given_yaml_file_when_loaded_then_returns_valid_capability_spec`
     - `TestDevSpec::test_given_dev_spec_when_outputs_schema_validates_model_dump_then_passes`

3. **Verify registry integration and tag search**
   - Add tests to `tests/test_archipelago_capability_specs.py`:
     - `TestRegistryIntegration::test_given_all_yaml_specs_when_registry_loaded_then_contains_12_capabilities`
     - `TestRegistryIntegration::test_given_registry_when_searched_by_archipelago_tag_then_returns_exactly_4`
     - `TestRegistryIntegration::test_given_each_archipelago_spec_when_name_queried_then_found_in_registry`

---

### PR 3: Archipelago Pipeline Plan & Planner Extension (Phase 2)

**Description**: Define the `GraphWiringPlan` for the Archipelago pipeline, extend `WiringPlanner` to support the `"archipelago-pipeline"` goal, and validate it with the existing 7-check validator.

**Acceptance Criteria Addressed**: #8, #9, #10, #11, #12

**Complexity**: M

**Dependencies**: PR 2 (capability specs must be registered for validation)

**Files created**:
- `src/agent_foundry/archipelago/archipelago_system.json`
- `tests/test_archipelago_pipeline_plan.py`

**Files modified**:
- `src/agent_foundry/planner/planner.py` (add `_ARCHIPELAGO_PIPELINE_PLAN` and register in `_GOAL_PLANS`)

**Commits**:

1. **Add static archipelago pipeline plan JSON and parse tests**
   - Create `src/agent_foundry/archipelago/archipelago_system.json` with the plan:
     ```
     goal: "archipelago-pipeline"
     nodes:
       - {id: "strategy", capability: "strategy_generate_product_brief", config: {}}
       - {id: "architecture", capability: "architecture_generate_feature_arch", config: {}}
       - {id: "spec", capability: "spec_generate_feature_spec", config: {}}
       - {id: "spec_approval_gate", capability: "human_approval_gate", config: {}}
       - {id: "dev_test", capability: "dev_implement_feature_tdd", config: {}}
     edges:
       - {source: "strategy", target: "architecture"}
       - {source: "architecture", target: "spec"}
       - {source: "spec", target: "spec_approval_gate"}
       - {source: "spec_approval_gate", target: "dev_test"}
     entry_point: "strategy"
     breakpoints: ["spec_approval_gate"]
     capability_versions:
       strategy_generate_product_brief: "1.0.0"
       architecture_generate_feature_arch: "1.0.0"
       spec_generate_feature_spec: "1.0.0"
       human_approval_gate: "1.0.0"
       dev_implement_feature_tdd: "1.0.0"
     ```
   - Create `tests/test_archipelago_pipeline_plan.py` with tests:
     - `TestParsePlan::test_given_pipeline_json_when_parsed_then_goal_is_archipelago_pipeline`
     - `TestParsePlan::test_given_pipeline_json_when_parsed_then_has_5_nodes`
     - `TestParsePlan::test_given_pipeline_json_when_parsed_then_has_4_edges`
     - `TestParsePlan::test_given_pipeline_json_when_parsed_then_entry_point_is_strategy`
     - `TestParsePlan::test_given_pipeline_json_when_parsed_then_breakpoints_contain_spec_approval_gate`
     - `TestParsePlan::test_given_pipeline_json_when_round_tripped_then_no_field_loss`
     - `TestParsePlan::test_given_pipeline_json_when_capability_versions_inspected_then_all_nodes_covered`

2. **Validate the pipeline plan against the registry**
   - Add tests to `tests/test_archipelago_pipeline_plan.py`:
     - `TestValidatePlan::test_given_pipeline_plan_and_full_registry_when_validated_then_no_errors`
     - `TestValidatePlan::test_given_pipeline_plan_when_duplicate_check_runs_then_no_duplicate_ids`
     - `TestValidatePlan::test_given_pipeline_plan_when_dangling_edge_check_runs_then_no_dangles`
     - `TestValidatePlan::test_given_pipeline_plan_when_breakpoint_check_runs_then_all_breakpoints_valid`
     - `TestValidatePlan::test_given_pipeline_plan_when_version_coverage_check_runs_then_all_covered`

3. **Extend WiringPlanner to support archipelago-pipeline goal**
   - Add `_ARCHIPELAGO_PIPELINE_PLAN` dict to `planner.py` following the exact pattern of `_DECISION_SUPPORT_PLAN`.
   - Register it in `_GOAL_PLANS` under key `"archipelago-pipeline"`.
   - Add tests to `tests/test_archipelago_pipeline_plan.py`:
     - `TestPlannerExtension::test_given_planner_with_registry_when_plan_archipelago_pipeline_then_returns_valid_plan`
     - `TestPlannerExtension::test_given_planner_when_plan_archipelago_pipeline_then_has_5_nodes`
     - `TestPlannerExtension::test_given_planner_when_plan_archipelago_pipeline_then_breakpoints_set`
     - `TestPlannerExtension::test_given_planner_when_plan_archipelago_pipeline_then_validates_against_registry`
   - Run existing planner tests to confirm no regressions.

---

### PR 4: LLM-Backed Handlers (Phase 3)

**Description**: Implement real handlers using `langchain-anthropic` for each pipeline stage, wire them into the compiler via `handler_registry`, and run end-to-end with tracing.

**Acceptance Criteria Addressed**: #13, #14, #15, #16, #17, #18

**Complexity**: L

**Dependencies**: PR 3 (pipeline plan and planner extension must exist)

**Files created**:
- `src/agent_foundry/archipelago/handlers.py`
- `src/agent_foundry/archipelago/prompts.py`
- `src/agent_foundry/archipelago/runner.py`
- `tests/test_archipelago_handlers.py`
- `tests/test_archipelago_e2e.py`

**Commits**:

1. **Add strategy handler with LLM call and schema enforcement**
   - Create `src/agent_foundry/archipelago/prompts.py` with prompt templates for each stage. Start with `STRATEGY_PROMPT` template that instructs the LLM to produce a `ProductBrief`-shaped JSON output.
   - Create `src/agent_foundry/archipelago/handlers.py` with `strategy_handler(state: dict) -> dict`.
     - Uses `ChatAnthropic` from `langchain-anthropic`.
     - Extracts `product_brief_input` from state.
     - Calls LLM with structured output (Pydantic model or JSON mode).
     - Returns state with `product_brief` key containing a `ProductBrief`-compatible dict.
   - Create `tests/test_archipelago_handlers.py` with tests (using mocked LLM):
     - `TestStrategyHandler::test_given_valid_input_when_handler_called_then_state_contains_product_brief`
     - `TestStrategyHandler::test_given_valid_input_when_handler_called_then_product_brief_validates_against_schema`
     - `TestStrategyHandler::test_given_empty_input_when_handler_called_then_raises_or_returns_error_state`

2. **Add architecture handler with LLM call**
   - Add `ARCHITECTURE_PROMPT` to `prompts.py`.
   - Add `architecture_handler(state: dict) -> dict` to `handlers.py`.
     - Reads `product_brief` from state, calls LLM, returns `feature_architecture`.
   - Add tests:
     - `TestArchitectureHandler::test_given_state_with_product_brief_when_called_then_state_contains_feature_architecture`
     - `TestArchitectureHandler::test_given_state_with_product_brief_when_called_then_feature_architecture_validates`

3. **Add spec handler with LLM call**
   - Add `SPEC_PROMPT` to `prompts.py`.
   - Add `spec_handler(state: dict) -> dict` to `handlers.py`.
     - Reads `feature_architecture`, calls LLM, returns `feature_spec` and `test_plan`.
   - Add tests:
     - `TestSpecHandler::test_given_state_with_architecture_when_called_then_state_contains_feature_spec_and_test_plan`
     - `TestSpecHandler::test_given_state_with_architecture_when_called_then_both_outputs_validate`

4. **Add dev/test handler with LLM call**
   - Add `DEV_TEST_PROMPT` to `prompts.py`.
   - Add `dev_test_handler(state: dict) -> dict` to `handlers.py`.
     - Reads `feature_spec` and `test_plan`, calls LLM, returns `code_patch` and `test_results`.
   - Add tests:
     - `TestDevTestHandler::test_given_state_with_spec_and_plan_when_called_then_state_contains_code_patch_and_test_results`
     - `TestDevTestHandler::test_given_state_with_spec_and_plan_when_called_then_both_outputs_validate`

5. **Add gate handler and handler registry**
   - Add `spec_approval_gate_handler(state: dict) -> dict` to `handlers.py`.
     - Reads `action_summary` from the spec output and returns `{approved: True, approver: "auto"}` (for automated runs; breakpoint pauses for human approval in real use).
   - Create `ARCHIPELAGO_HANDLERS` dict mapping capability names to handler functions (following the `DEMO_HANDLERS` pattern in `runner.py`).
   - Add tests:
     - `TestGateHandler::test_given_state_with_spec_when_gate_called_then_returns_approved`
     - `TestHandlerRegistry::test_given_archipelago_handlers_when_all_keys_checked_then_all_5_capabilities_present`
     - `TestHandlerRegistry::test_given_each_handler_in_registry_when_checked_then_is_callable`

6. **Add end-to-end runner and integration tests with tracing**
   - Create `src/agent_foundry/archipelago/runner.py` following the pattern of `demo/runner.py`:
     - `load_archipelago_plan() -> GraphWiringPlan`
     - `run_archipelago(product_brief_input: str, registry=None, plan=None) -> dict`
     - Wires `ARCHIPELAGO_HANDLERS` into `compile_plan()`.
   - Create `tests/test_archipelago_e2e.py` with tests (mocked LLM):
     - `TestEndToEnd::test_given_valid_input_when_pipeline_runs_then_final_state_has_all_6_artifacts`
     - `TestEndToEnd::test_given_valid_input_when_pipeline_runs_then_all_artifacts_validate`
     - `TestEndToEnd::test_given_pipeline_with_tracer_when_run_then_5_spans_exported`
     - `TestEndToEnd::test_given_pipeline_with_tracer_when_run_then_all_spans_have_ok_status`
     - `TestEndToEnd::test_given_pipeline_with_tracer_when_run_then_all_spans_have_nonzero_duration`
   - Run all existing tests to confirm no regressions.

---

### PR 5: Checkpoint/Resume (Phase 4)

**Description**: Wire LangGraph's built-in checkpointing into the compiler so that pipeline execution can pause at breakpoints and resume from checkpoints without re-executing completed stages.

**Acceptance Criteria Addressed**: #19, #20, #21, #22

**Complexity**: M

**Dependencies**: PR 3 (pipeline plan with breakpoints). Can be developed in parallel with PR 4 using stub handlers.

**Files modified**:
- `src/agent_foundry/compiler/compiler.py` (extend `compile_plan()` to wire checkpointer when `plan.persistence` is set)

**Files created**:
- `tests/test_archipelago_checkpoint.py`

**Commits**:

1. **Extend compile_plan to wire LangGraph checkpointer when persistence is configured**
   - Modify `compile_plan()` in `compiler.py`:
     - When `plan.persistence` is not `None`, instantiate a checkpointer based on `plan.persistence.backend` (start with `"memory"` using LangGraph's `MemorySaver`).
     - Pass the checkpointer to `graph.compile(checkpointer=checkpointer)`.
     - Pass `interrupt_before` for nodes listed in `plan.breakpoints`.
   - Create `tests/test_archipelago_checkpoint.py` with tests:
     - `TestCheckpointCompilation::test_given_plan_with_persistence_when_compiled_then_graph_has_checkpointer`
     - `TestCheckpointCompilation::test_given_plan_without_persistence_when_compiled_then_no_checkpointer`
     - `TestCheckpointCompilation::test_given_plan_with_breakpoints_and_persistence_when_compiled_then_interrupt_before_set`

2. **Implement pause-at-breakpoint behavior**
   - Add tests:
     - `TestBreakpointPause::test_given_pipeline_with_breakpoint_when_invoked_then_execution_pauses_at_gate`
     - `TestBreakpointPause::test_given_paused_execution_when_state_inspected_then_strategy_architecture_spec_artifacts_present`
     - `TestBreakpointPause::test_given_paused_execution_when_state_inspected_then_dev_test_artifacts_absent`
   - Implementation may require configuring the LangGraph `invoke()` call with the `thread_id` from `plan.persistence.thread_id` via a `config` dict: `{"configurable": {"thread_id": plan.persistence.thread_id}}`.

3. **Implement resume-from-checkpoint behavior**
   - Add tests:
     - `TestCheckpointResume::test_given_paused_execution_when_resumed_with_approval_then_completes_to_end`
     - `TestCheckpointResume::test_given_paused_execution_when_resumed_then_prior_nodes_not_re_executed`
     - `TestCheckpointResume::test_given_checkpoint_and_new_graph_from_same_plan_when_loaded_then_resumes_correctly`
   - Implementation uses LangGraph's `graph.invoke(None, config)` pattern to resume from the last checkpoint, or `Command(resume=...)` if using interrupt-based flow.

---

## Dependency Graph

```
PR 1 (Artifact Models)
  |
  v
PR 2 (Capability Specs)
  |
  v
PR 3 (Pipeline Plan + Planner)
  |          |
  v          v
PR 4        PR 5
(Handlers)  (Checkpoint/Resume)
```

PR 4 and PR 5 are independent of each other and can be developed in parallel once PR 3 is merged. PR 5 can use stub/passthrough handlers for testing (following the existing pattern in `test_compiler_basic.py`).

---

## Implementation Notes

### Patterns to Follow

- **Capability spec YAML structure**: Follow the exact format of existing specs (e.g., `src/archipelago/capabilities/human_approval_gate.yaml`). Fields: `name`, `description`, `version`, `implementation`, `inputs_schema`, `outputs_schema`, `tags`, `quality_controls`.
- **Handler function signature**: `def handler(state: dict[str, Any]) -> dict[str, Any]` -- takes full state, returns merged state. Follow `_retriever_handler` in `demo/runner.py`.
- **Handler registry**: A plain `dict[str, Callable]` mapping capability names to handler functions. Follow `DEMO_HANDLERS` in `demo/runner.py`.
- **Plan definition**: Static dict in `planner.py` registered in `_GOAL_PLANS`. Follow `_DECISION_SUPPORT_PLAN`.
- **Test structure**: Class-based grouping with descriptive test names. Fixtures for shared setup (registry, plans). Follow `tests/test_compiler_basic.py` and `tests/test_wiring_plan.py`.
- **Module structure**: New code goes under `src/agent_foundry/archipelago/`. Do not modify existing modules except `planner.py` (PR 3) and `compiler.py` (PR 5).

### LLM Mocking Strategy for Tests

All handler tests (PR 4) must mock the LLM to avoid real API calls and ensure deterministic, fast tests. Use `unittest.mock.patch` to replace `ChatAnthropic` with a mock that returns pre-defined structured outputs matching the expected Pydantic model shapes. The end-to-end tests similarly use mocked handlers -- not mocked LLMs -- to test the full pipeline wiring without any external dependencies.

### Risk Mitigations

- **Schema drift**: Each commit that adds a model also adds a test verifying the model's `model_json_schema()` matches the YAML spec's `outputs_schema`. This catches drift immediately.
- **Existing test regressions**: Each PR must run the full test suite before merge. The new capabilities added to `src/archipelago/capabilities/` will increase the registry size, so any test that asserts `len(registry) == 8` must be updated.
- **LLM output instability**: Handlers should use Pydantic structured output mode (`with_structured_output()`) to constrain LLM responses. Tests use mocks so instability only affects manual/integration testing.
