# Feature Specification: Claude Code Docker Worker Integration

## Objective

Replace the placeholder `dev_implement_feature_tdd` handler with a real implementation that delegates coding work to Claude Code (CC) running inside an ephemeral Docker container. The orchestrator manages the full lifecycle -- container provisioning, repo checkout, session management, structured progress reporting, interactive breakpoints (clarification/permission), and crash recovery -- while CC operates as a self-contained TDD worker iterating across the spec's PRs and commits.

> **Note — Adapter Protocol Evolution**: The original PTY-based session management design has been superseded by a structured WebSocket protocol using the headless adapter (`claude -p --output-format stream-json`). See [`docs/archipelago/adapter_protocol_spec.md`](../adapter_protocol_spec.md) for the full protocol specification, including message types, status lifecycle, task completion signaling, gate node integration, and architecture decisions.

### Success Criteria

1. The `coding.implement_feature_from_spec` capability accepts a typed input (repo ref, feature spec, constraints, test commands, gates) and returns a typed output (result summary, workspace ref, patches/PRs, evidence) -- validated against JSON Schema at runtime.
2. Each invocation spins up a dedicated Docker container with the target repo checked out, runs CC under a persistent PTY, and tears down the container on completion or timeout.
3. CC's stdout/stderr streams to the orchestrator in real time for log capture and trace correlation.
4. When CC emits an `ARCHIPELAGO_NEED_CLARIFICATION` or `ARCHIPELAGO_NEED_PERMISSION` interrupt, the orchestrator pauses the pipeline at a breakpoint, surfaces the request, and resumes the PTY session after human response.
5. The container enforces the safety baseline: non-root user, dropped capabilities, seccomp/AppArmor, read-only base filesystem, writable workspace volume only, resource limits, no sensitive host mounts.
6. CC writes structured progress checkpoints to `progress.jsonl` in the workspace using the defined event schema (`commit_started`, `commit_green`, `pr_completed`, `blocked`).
7. If a live session dies (crash, eviction, timeout), the orchestrator can restore workspace state into a fresh container and resume from the last checkpoint boundary.
8. All existing tests remain green throughout; no regressions.

---

## Constraints

### Technical
- Must integrate with the existing `CapabilityRegistry`, `GraphWiringPlan`, `compile_plan()`, `ExecutionTracer`, and breakpoint infrastructure without forking or duplicating them.
- Handler signature remains `def handler(state: dict[str, Any]) -> dict[str, Any]` -- the Docker worker handler wraps the container lifecycle behind this interface.
- Pydantic v2 models for all new data structures (container config, progress events, interrupt payloads, worker result).
- The existing `dev_implement_feature_tdd` capability spec YAML (`src/archipelago/capabilities/dev_implement_feature_tdd.yaml`) will be replaced by a new `coding_implement_feature_from_spec` capability spec with expanded I/O schemas. The old spec is retained for backward compatibility but tagged as `deprecated`.
- Docker SDK for Python (`docker` package) for container management; no shell-out to `docker` CLI.
- Python 3.13 (per `pyproject.toml`), PDM for package management.
- LangGraph `StateGraph` as the execution engine; existing checkpoint/resume mechanics (PR 5 of the orchestrator spec) are prerequisites for the breakpoint flow.

### Scope
- **In scope**: Container lifecycle management, PTY session management, stdout/stderr streaming, structured progress checkpoints, interrupt protocol (clarification/permission), safety baseline enforcement, crash recovery/resume, capability spec and handler integration, and unit/integration tests with Docker mocked.
- **Out of scope**: Codex integration (CC only for now), multi-container parallelism (one container per run), network policy enforcement beyond basic isolation, custom seccomp/AppArmor profiles (use Docker defaults with capability drops), CI/CD integration, cost budgeting/metering, and the spec-revise or implement-test-fix feedback loops.

### Quality
- TDD throughout: tests written before implementation, red-green-refactor.
- Each PR independently mergeable; system stays in a working state after each merge.
- Each commit atomic and focused on a single concern.
- Test naming follows Given/When/Then convention.
- All Docker interactions mocked in unit tests; integration tests (marked `@pytest.mark.integration`) require a running Docker daemon and are excluded from default test runs.

### Time
- Phase 1 (data models + progress schema) is the foundation; all subsequent phases depend on it.
- Phase 2 (container lifecycle) and Phase 3 (PTY + streaming) are sequential.
- Phase 4 (interrupt protocol) depends on Phase 3.
- Phase 5 (recovery/resume) depends on Phase 2 and Phase 3.
- Phase 6 (capability spec + handler wiring) depends on all prior phases.

---

## Acceptance Criteria

### Phase 1: Data Models & Progress Event Schema

1. **Given** the `archipelago.docker_worker.models` module exists, **when** a `WorkerInput` is instantiated with fields `repo_ref: str`, `feature_spec: dict`, `constraints: WorkerConstraints`, `test_commands: list[str]`, `gates: list[str]`, **then** it validates successfully and round-trips through `model_dump_json()` / `model_validate_json()` with no field loss.

2. **Given** the `WorkerConstraints` model, **when** instantiated with `timeout_seconds: int`, `max_cost_usd: float | None`, `allowed_commands: list[str]`, `network_policy: str`, **then** it validates and defaults `max_cost_usd` to `None` and `network_policy` to `"none"`.

3. **Given** the `WorkerResult` model, **when** instantiated with `result_summary: str`, `workspace_ref: str`, `patches: list[PatchInfo]`, `evidence: list[CommitEvidence]`, `status: Literal["completed", "failed", "interrupted", "timed_out"]`, **then** it validates and round-trips.

4. **Given** a `PatchInfo` model with fields `pr_id: str`, `branch_name: str`, `files_changed: list[str]`, `diff_summary: str`, **then** it validates and round-trips.

5. **Given** a `CommitEvidence` model with fields `commit_id: str`, `pr_id: str`, `test_commands_run: list[str]`, `test_output: str`, `tests_passed: int`, `tests_failed: int`, `all_green: bool`, **then** it validates and round-trips.

6. **Given** a `ProgressEvent` model, **when** instantiated with `type: Literal["commit_started", "commit_green", "pr_completed", "blocked"]`, `pr_id: str`, `commit_id: str`, `files_changed: list[str]`, `tests_added: list[str]`, `tests_run: list[TestRunRecord]`, `status: str`, `notes: str`, `timestamp: float`, **then** it validates and round-trips.

7. **Given** any model above, **when** instantiated with missing required fields, **then** a Pydantic `ValidationError` is raised listing the missing fields.

### Phase 2: Container Lifecycle Manager

8. **Given** a `ContainerManager` initialized with a Docker client, **when** `create_container(image, repo_ref, workspace_volume)` is called, **then** it returns a `ContainerHandle` with a unique container ID, and the container is created with the safety baseline configuration (non-root user, dropped capabilities, read-only rootfs, writable workspace bind mount, resource limits).

9. **Given** a running container via `ContainerHandle`, **when** `start()` is called, **then** the container transitions to `running` state and the target repo is cloned/checked out at `repo_ref` inside the workspace volume.

10. **Given** a running container, **when** `stop()` is called, **then** the container is stopped gracefully (SIGTERM, then SIGKILL after grace period) and the container handle status becomes `stopped`.

11. **Given** a running or stopped container, **when** `destroy()` is called, **then** the container and its anonymous volumes are removed, but the named workspace volume is retained.

12. **Given** a `ContainerManager`, **when** `create_container()` is called with resource limits `cpu_quota`, `mem_limit`, `pids_limit`, **then** the Docker container is configured with those limits.

13. **Given** a `ContainerManager`, **when** `create_container()` is called, **then** no sensitive host filesystem paths are mounted and environment variables are filtered through an explicit allowlist.

### Phase 3: PTY Session & Streaming

> **Evolution note**: PTY session management (`SessionManager`) has been superseded by the adapter protocol for the handler's communication path. The handler now uses a WebSocket server (`_HandlerWSServer`) and processes structured protocol messages. `SessionManager` is retained for recovery flows and backward compatibility. New deployments should use the headless adapter — see `adapter_protocol_spec.md`.

14. **Given** a running container with CC installed, **when** `launch_session(container_handle, command)` is called, **then** a persistent PTY session is established via `docker exec` with TTY allocation, and a `SessionHandle` is returned.

15. **Given** an active `SessionHandle`, **when** stdout/stderr is produced by CC, **then** the output is streamed line-by-line to a registered callback (the orchestrator's log collector), with each line tagged with a monotonic timestamp and the container ID.

16. **Given** an active `SessionHandle`, **when** `send_input(text)` is called, **then** the text is written to the PTY's stdin and CC receives it as interactive input.

17. **Given** an active `SessionHandle`, **when** the PTY process exits (CC finishes), **then** the session handle status transitions to `exited` with the exit code captured.

18. **Given** an active `SessionHandle`, **when** `pause()` is called, **then** the session remains alive (container + PTY process running) but the orchestrator stops consuming output until `resume()` is called.

### Phase 4: Interrupt Protocol

19. **Given** a stream of CC output lines, **when** a line matches the pattern `ARCHIPELAGO_NEED_CLARIFICATION { ... }`, **then** the `InterruptDetector` parses it into a `ClarificationRequest` model with fields `question: str`, `options: list[str]`, `default: str | None`, `blocking: bool`.

20. **Given** a stream of CC output lines, **when** a line matches the pattern `ARCHIPELAGO_NEED_PERMISSION { ... }`, **then** the `InterruptDetector` parses it into a `PermissionRequest` model with fields `action: str`, `risk_level: str`, `why_needed: str`, `alternatives: list[str]`.

21. **Given** a detected `ClarificationRequest` with `blocking=True`, **when** the interrupt is raised, **then** the orchestrator triggers a pipeline breakpoint (via the existing breakpoint mechanism), the PTY session is paused, and the request is surfaced as a `breakpoint_payload` in the pipeline state.

22. **Given** a paused breakpoint with a `ClarificationRequest`, **when** the human provides a response and the pipeline is resumed, **then** the response text is sent to the PTY session via `send_input()` and CC continues processing.

23. **Given** a detected `PermissionRequest`, **when** `risk_level` is `"high"`, **then** the orchestrator always triggers a breakpoint regardless of auto-approval settings.

24. **Given** a detected `PermissionRequest`, **when** `risk_level` is `"low"` and auto-approval is enabled in `WorkerConstraints`, **then** the orchestrator auto-responds with approval without triggering a breakpoint.

### Phase 5: Progress Checkpoint Parsing & Recovery/Resume

25. **Given** a workspace volume with a `progress.jsonl` file, **when** `parse_progress(workspace_path)` is called, **then** it returns a list of `ProgressEvent` objects in chronological order, each validated against the event schema.

26. **Given** a `progress.jsonl` with events `[commit_started(pr1, c1), commit_green(pr1, c1), commit_started(pr1, c2), blocked(pr1, c2)]`, **when** `get_resume_point(events)` is called, **then** it returns `ResumePoint(pr_id="pr1", commit_id="c2", status="blocked")` indicating work should resume at commit c2 of PR 1.

27. **Given** a dead container session (container crashed or was evicted), **when** `recover_session(workspace_volume, feature_spec, last_checkpoint)` is called, **then** a fresh container is created, the workspace volume is re-mounted, and CC is restarted with the feature spec plus context from the last checkpoint.

28. **Given** a recovered session, **when** CC resumes, **then** it starts from the PR/commit boundary identified by the last `ProgressEvent` and does not re-execute previously completed commits (as indicated by `commit_green` events).

29. **Given** a workspace volume from a crashed session, **when** recovery is attempted, **then** the workspace's git state (commit SHA + working tree diff) and the CC transcript (or run summary) are persisted before the fresh container starts.

### Phase 6: Capability Spec, Handler Wiring & End-to-End Integration

> **Evolution note**: The `docker_worker_handler` has been rewritten to use the WebSocket protocol (see `adapter_protocol_spec.md` PR 3). It no longer uses `SessionManager`, `InterruptDetector`, or `InterruptHandler` directly. Instead, it starts a `_HandlerWSServer`, processes `OutputMessage`, `InterruptMessage`, and `StatusMessage` from the adapter, and sends `InputMessage`/`ControlMessage` back. Interrupt handling is done inline by inspecting `InterruptMessage` payloads. The handler's external interface (`def handler(state) -> state`) is unchanged.

30. **Given** a YAML capability spec file for `coding.implement_feature_from_spec`, **when** loaded via `load_capability_spec()`, **then** it returns a valid `CapabilitySpec` with `inputs_schema` matching `WorkerInput` and `outputs_schema` matching `WorkerResult`.

31. **Given** the capability spec registered in the registry, **when** searched by tag `"archipelago"` and `"docker-worker"`, **then** it is returned in the results.

32. **Given** a `docker_worker_handler(state: dict) -> dict` function and a state dict containing `worker_input` with a valid `WorkerInput`, **when** the handler is called, **then** it orchestrates the full lifecycle (create container, launch session, stream output, collect progress events, handle interrupts, tear down) and returns a state dict with `worker_result` containing a valid `WorkerResult`.

33. **Given** the `docker_worker_handler` wired into the `ARCHIPELAGO_HANDLERS` registry under `coding.implement_feature_from_spec`, **when** `compile_plan()` is called with the updated pipeline plan, **then** the handler is resolved and the graph compiles without error.

34. **Given** an end-to-end run with an `ExecutionTracer`, **when** the Docker worker node executes, **then** a tracing span is emitted with `node_id`, `capability`, `start_time`, `end_time`, and `status`, and child spans are emitted for container lifecycle events (create, start, session_launch, session_end, stop, destroy).

35. **Given** the updated pipeline plan with `coding.implement_feature_from_spec` replacing `dev_implement_feature_tdd` at the `dev_test` node, **when** `validate_plan()` is called against the full registry, **then** all 7 validator checks pass.

---

## PR/Commit Slices

### PR 1: Docker Worker Data Models & Progress Event Schema (Phase 1)

**Description**: Define all Pydantic models for the Docker worker subsystem: inputs, outputs, constraints, progress events, interrupt payloads, and resume points. These models are the typed contracts that all subsequent phases build on.

**Acceptance Criteria Addressed**: #1, #2, #3, #4, #5, #6, #7

**Complexity**: S

**Dependencies**: None (builds on existing Pydantic patterns in `archipelago.models`)

**Files created**:
- `src/archipelago/__init__.py` (if not yet present)
- `src/archipelago/docker_worker/__init__.py`
- `src/archipelago/docker_worker/models.py`
- `tests/archipelago/test_docker_worker_models.py`

**Commits**:

1. **Add WorkerInput, WorkerConstraints, and WorkerResult models**
   - Create `src/archipelago/docker_worker/__init__.py` (empty package marker).
   - Create `src/archipelago/docker_worker/models.py` with:
     - `WorkerConstraints` fields: `timeout_seconds: int` (default 3600), `max_cost_usd: float | None` (default None), `allowed_commands: list[str]` (default []), `network_policy: str` (default "none").
     - `WorkerInput` fields: `repo_ref: str`, `feature_spec: dict[str, Any]`, `constraints: WorkerConstraints`, `test_commands: list[str]`, `gates: list[str]` (default []).
     - `WorkerResult` fields: `result_summary: str`, `workspace_ref: str`, `patches: list[PatchInfo]`, `evidence: list[CommitEvidence]`, `status: Literal["completed", "failed", "interrupted", "timed_out"]`.
     - `PatchInfo` fields: `pr_id: str`, `branch_name: str`, `files_changed: list[str]`, `diff_summary: str`.
     - `CommitEvidence` fields: `commit_id: str`, `pr_id: str`, `test_commands_run: list[str]`, `test_output: str`, `tests_passed: int`, `tests_failed: int`, `all_green: bool`.
   - Create `tests/archipelago/test_docker_worker_models.py` with tests:
     - `TestWorkerInput::test_given_valid_fields_when_instantiated_then_validates`
     - `TestWorkerInput::test_given_valid_instance_when_json_round_tripped_then_no_field_loss`
     - `TestWorkerInput::test_given_missing_required_field_when_instantiated_then_raises_validation_error`
     - `TestWorkerConstraints::test_given_no_args_when_instantiated_then_defaults_applied`
     - `TestWorkerResult::test_given_valid_fields_when_instantiated_then_validates`
     - `TestWorkerResult::test_given_valid_instance_when_json_round_tripped_then_no_field_loss`
     - `TestPatchInfo::test_given_valid_fields_when_instantiated_then_validates`
     - `TestCommitEvidence::test_given_valid_fields_when_instantiated_then_validates`

2. **Add ProgressEvent, TestRunRecord, interrupt request models, and ResumePoint**
   - Add to `models.py`:
     - `TestRunRecord` fields: `command: str`, `exit_code: int`, `output_summary: str`.
     - `ProgressEvent` fields: `type: Literal["commit_started", "commit_green", "pr_completed", "blocked"]`, `pr_id: str`, `commit_id: str`, `files_changed: list[str]` (default []), `tests_added: list[str]` (default []), `tests_run: list[TestRunRecord]` (default []), `status: str`, `notes: str` (default ""), `timestamp: float`.
     - `ClarificationRequest` fields: `question: str`, `options: list[str]` (default []), `default: str | None` (default None), `blocking: bool` (default True).
     - `PermissionRequest` fields: `action: str`, `risk_level: Literal["low", "medium", "high"]`, `why_needed: str`, `alternatives: list[str]` (default []).
     - `ResumePoint` fields: `pr_id: str`, `commit_id: str`, `status: str`.
   - Add tests:
     - `TestProgressEvent::test_given_valid_commit_started_when_instantiated_then_validates`
     - `TestProgressEvent::test_given_valid_instance_when_json_round_tripped_then_no_field_loss`
     - `TestProgressEvent::test_given_invalid_type_when_instantiated_then_raises_validation_error`
     - `TestClarificationRequest::test_given_valid_fields_when_instantiated_then_validates`
     - `TestClarificationRequest::test_given_defaults_when_instantiated_then_blocking_is_true`
     - `TestPermissionRequest::test_given_valid_fields_when_instantiated_then_validates`
     - `TestPermissionRequest::test_given_invalid_risk_level_when_instantiated_then_raises_validation_error`
     - `TestResumePoint::test_given_valid_fields_when_instantiated_then_validates`

---

### PR 2: Container Lifecycle Manager (Phase 2)

**Description**: Implement the `ContainerManager` class that wraps Docker SDK operations for creating, starting, stopping, and destroying containers with the safety baseline enforced. All Docker SDK calls are mocked in unit tests.

**Acceptance Criteria Addressed**: #8, #9, #10, #11, #12, #13

**Complexity**: M

**Dependencies**: PR 1 (models for `WorkerConstraints` used in container configuration)

**Files created**:
- `src/archipelago/docker_worker/container.py`
- `src/archipelago/docker_worker/errors.py`
- `tests/archipelago/test_docker_worker_container.py`

**Commits**:

1. **Add ContainerHandle model and ContainerManager skeleton with create_container**
   - Create `src/archipelago/docker_worker/errors.py` with error classes: `ContainerCreationError`, `ContainerLifecycleError`, `SessionError`.
   - Create `src/archipelago/docker_worker/container.py` with:
     - `ContainerHandle` dataclass: `container_id: str`, `status: str`, `workspace_path: str`, `created_at: float`.
     - `ContainerManager.__init__(self, client, default_image, env_allowlist)`.
     - `ContainerManager.create_container(self, image, repo_ref, workspace_volume, constraints)` that calls `client.containers.create()` with security configuration:
       - `user`: non-root UID (e.g., 1000)
       - `cap_drop`: ["ALL"]
       - `read_only`: True
       - `tmpfs`: {"/tmp": "size=256m"}
       - `volumes`: workspace bind mount (rw)
       - `mem_limit`, `cpu_quota`, `pids_limit` from constraints
       - `environment`: filtered through `env_allowlist`
   - Create `tests/archipelago/test_docker_worker_container.py` with tests (Docker SDK mocked):
     - `TestCreateContainer::test_given_valid_config_when_create_called_then_returns_container_handle`
     - `TestCreateContainer::test_given_valid_config_when_create_called_then_container_uses_non_root_user`
     - `TestCreateContainer::test_given_valid_config_when_create_called_then_all_capabilities_dropped`
     - `TestCreateContainer::test_given_valid_config_when_create_called_then_rootfs_is_read_only`
     - `TestCreateContainer::test_given_resource_limits_when_create_called_then_limits_applied`
     - `TestCreateContainer::test_given_env_vars_when_create_called_then_only_allowlisted_vars_passed`

2. **Add start, stop, and destroy lifecycle methods**
   - Add to `ContainerManager`:
     - `start(handle)`: calls `container.start()`, runs repo clone/checkout command via `exec_run()`, updates handle status.
     - `stop(handle, timeout=10)`: calls `container.stop(timeout=timeout)`, updates handle status.
     - `destroy(handle, remove_volume=False)`: calls `container.remove(v=not remove_volume)`.
   - Add tests:
     - `TestStartContainer::test_given_created_container_when_start_called_then_status_becomes_running`
     - `TestStartContainer::test_given_created_container_when_start_called_then_repo_cloned_at_ref`
     - `TestStopContainer::test_given_running_container_when_stop_called_then_status_becomes_stopped`
     - `TestStopContainer::test_given_running_container_when_stop_called_then_graceful_shutdown_attempted`
     - `TestDestroyContainer::test_given_stopped_container_when_destroy_called_then_container_removed`
     - `TestDestroyContainer::test_given_stopped_container_when_destroy_with_retain_volume_then_workspace_preserved`

---

### PR 3: PTY Session Management & Output Streaming (Phase 3)

**Description**: Implement the `SessionManager` that establishes a persistent PTY session inside a running container, streams stdout/stderr to the orchestrator via callbacks, and supports sending input to the PTY's stdin.

**Acceptance Criteria Addressed**: #14, #15, #16, #17, #18

**Complexity**: M

**Dependencies**: PR 2 (container must be running to establish a session)

**Files created**:
- `src/archipelago/docker_worker/session.py`
- `tests/archipelago/test_docker_worker_session.py`

**Commits**:

1. **Add SessionHandle model and SessionManager with launch_session**
   - Create `src/archipelago/docker_worker/session.py` with:
     - `SessionHandle` dataclass: `exec_id: str`, `container_id: str`, `status: Literal["running", "paused", "exited"]`, `exit_code: int | None`, `started_at: float`.
     - `SessionManager.__init__(self, container_manager)`.
     - `SessionManager.launch_session(self, container_handle, command)`: calls Docker exec with `tty=True`, `stdin=True`, `stream=True`; returns `SessionHandle`.
   - Create `tests/archipelago/test_docker_worker_session.py` with tests (Docker SDK mocked):
     - `TestLaunchSession::test_given_running_container_when_launch_called_then_returns_session_handle`
     - `TestLaunchSession::test_given_running_container_when_launch_called_then_tty_allocated`
     - `TestLaunchSession::test_given_running_container_when_launch_called_then_status_is_running`

2. **Add output streaming with callback registration**
   - Add to `SessionManager`:
     - `register_output_callback(self, callback: Callable[[str, str, float], None])`: registers a callback receiving `(line, container_id, timestamp)`.
     - `_stream_output(self, session_handle)`: background task that reads from the exec stream, splits into lines, and invokes registered callbacks.
   - Add tests:
     - `TestOutputStream::test_given_active_session_when_cc_produces_output_then_callback_invoked_per_line`
     - `TestOutputStream::test_given_active_session_when_callback_invoked_then_line_tagged_with_container_id`
     - `TestOutputStream::test_given_active_session_when_callback_invoked_then_line_tagged_with_timestamp`
     - `TestOutputStream::test_given_multiple_callbacks_when_output_produced_then_all_callbacks_invoked`

3. **Add send_input, pause/resume, and exit detection**
   - Add to `SessionManager`:
     - `send_input(session_handle, text)`: writes to the exec socket's stdin.
     - `pause(session_handle)`: stops output consumption (sets internal flag); container and PTY remain alive.
     - `resume(session_handle)`: resumes output consumption.
     - Exit detection: when the exec stream closes, update `SessionHandle.status` to `"exited"` and capture `exit_code`.
   - Add tests:
     - `TestSendInput::test_given_active_session_when_send_input_called_then_text_written_to_stdin`
     - `TestPauseResume::test_given_active_session_when_paused_then_status_is_paused`
     - `TestPauseResume::test_given_paused_session_when_resumed_then_status_is_running`
     - `TestPauseResume::test_given_paused_session_when_output_produced_then_callback_not_invoked_until_resume`
     - `TestExitDetection::test_given_session_when_process_exits_then_status_is_exited`
     - `TestExitDetection::test_given_session_when_process_exits_then_exit_code_captured`

---

### PR 4: Interrupt Protocol (Phase 4)

**Description**: Implement the `InterruptDetector` that monitors CC output for `ARCHIPELAGO_NEED_CLARIFICATION` and `ARCHIPELAGO_NEED_PERMISSION` markers, parses them into typed models, and integrates with the orchestrator's breakpoint mechanism.

**Acceptance Criteria Addressed**: #19, #20, #21, #22, #23, #24

**Complexity**: M

**Dependencies**: PR 3 (output streaming provides the lines to scan), PR 1 (interrupt request models)

**Files created**:
- `src/archipelago/docker_worker/interrupts.py`
- `tests/archipelago/test_docker_worker_interrupts.py`

**Commits**:

1. **Add InterruptDetector with pattern matching for clarification and permission**
   - Create `src/archipelago/docker_worker/interrupts.py` with:
     - `InterruptDetector.__init__(self, on_clarification: Callable, on_permission: Callable)`.
     - `InterruptDetector.scan_line(self, line: str) -> ClarificationRequest | PermissionRequest | None`: uses regex to detect `ARCHIPELAGO_NEED_CLARIFICATION { json }` and `ARCHIPELAGO_NEED_PERMISSION { json }` patterns; parses JSON payload into the corresponding Pydantic model.
   - Create `tests/archipelago/test_docker_worker_interrupts.py` with tests:
     - `TestInterruptDetector::test_given_clarification_line_when_scanned_then_returns_clarification_request`
     - `TestInterruptDetector::test_given_permission_line_when_scanned_then_returns_permission_request`
     - `TestInterruptDetector::test_given_normal_output_line_when_scanned_then_returns_none`
     - `TestInterruptDetector::test_given_malformed_json_after_marker_when_scanned_then_returns_none_and_logs_warning`
     - `TestInterruptDetector::test_given_clarification_request_when_parsed_then_all_fields_populated`
     - `TestInterruptDetector::test_given_permission_request_when_parsed_then_risk_level_validated`

2. **Add breakpoint integration for blocking interrupts**
   - Add to `interrupts.py`:
     - `InterruptHandler.__init__(self, session_manager, detector, auto_approve_low_risk: bool)`.
     - `InterruptHandler.handle_interrupt(self, request, session_handle, state) -> dict`: for blocking clarification requests and high-risk permission requests, pauses the session and returns a state update with `breakpoint_payload` set. For low-risk permissions with auto-approval enabled, sends approval to stdin and returns state unchanged.
   - Add tests:
     - `TestInterruptHandler::test_given_blocking_clarification_when_handled_then_session_paused`
     - `TestInterruptHandler::test_given_blocking_clarification_when_handled_then_breakpoint_payload_set_in_state`
     - `TestInterruptHandler::test_given_high_risk_permission_when_handled_then_session_paused`
     - `TestInterruptHandler::test_given_low_risk_permission_with_auto_approve_when_handled_then_approval_sent`
     - `TestInterruptHandler::test_given_low_risk_permission_without_auto_approve_when_handled_then_session_paused`

3. **Add resume-after-interrupt flow**
   - Add to `InterruptHandler`:
     - `resume_after_response(self, response_text, session_handle)`: sends `response_text` to the PTY via `send_input()` and calls `session_manager.resume()`.
   - Add tests:
     - `TestResumeAfterInterrupt::test_given_paused_session_when_response_provided_then_input_sent_to_pty`
     - `TestResumeAfterInterrupt::test_given_paused_session_when_response_provided_then_session_resumed`
     - `TestResumeAfterInterrupt::test_given_resumed_session_when_cc_continues_then_output_streaming_resumes`

---

### PR 5: Progress Checkpoint Parsing & Recovery/Resume (Phase 5)

**Description**: Implement progress checkpoint file parsing and the recovery/resume flow that restores a crashed session into a fresh container from the last known good boundary.

**Acceptance Criteria Addressed**: #25, #26, #27, #28, #29

**Complexity**: M

**Dependencies**: PR 2 (container lifecycle for recovery), PR 3 (session management for relaunch), PR 1 (ProgressEvent, ResumePoint models)

**Files created**:
- `src/archipelago/docker_worker/progress.py`
- `src/archipelago/docker_worker/recovery.py`
- `tests/archipelago/test_docker_worker_progress.py`
- `tests/archipelago/test_docker_worker_recovery.py`

**Commits**:

1. **Add progress.jsonl parser and resume point calculation**
   - Create `src/archipelago/docker_worker/progress.py` with:
     - `parse_progress(workspace_path: Path) -> list[ProgressEvent]`: reads `progress.jsonl`, parses each line as a `ProgressEvent`, returns chronologically sorted list.
     - `get_resume_point(events: list[ProgressEvent]) -> ResumePoint | None`: scans events in reverse to find the last incomplete boundary -- returns `ResumePoint` with the PR/commit where work should resume. Returns `None` if all work is complete.
   - Create `tests/archipelago/test_docker_worker_progress.py` with tests:
     - `TestParseProgress::test_given_valid_jsonl_file_when_parsed_then_returns_progress_events`
     - `TestParseProgress::test_given_empty_file_when_parsed_then_returns_empty_list`
     - `TestParseProgress::test_given_invalid_json_line_when_parsed_then_skips_line_and_logs_warning`
     - `TestParseProgress::test_given_events_out_of_order_when_parsed_then_returns_sorted_by_timestamp`
     - `TestGetResumePoint::test_given_all_commits_green_when_calculated_then_returns_none`
     - `TestGetResumePoint::test_given_blocked_at_commit_when_calculated_then_returns_that_commit`
     - `TestGetResumePoint::test_given_commit_started_but_no_green_when_calculated_then_returns_that_commit`
     - `TestGetResumePoint::test_given_pr_completed_and_next_pr_started_when_calculated_then_returns_next_pr_commit`

2. **Add workspace state persistence for crash recovery**
   - Create `src/archipelago/docker_worker/recovery.py` with:
     - `persist_workspace_state(workspace_path: Path, output_path: Path)`: captures git commit SHA, working tree diff, and copies `progress.jsonl` and any CC transcript files to `output_path`.
     - `WorkspaceSnapshot` model: `commit_sha: str`, `working_tree_diff: str`, `progress_events: list[ProgressEvent]`, `transcript_path: str | None`.
   - Add to `tests/archipelago/test_docker_worker_recovery.py`:
     - `TestPersistWorkspaceState::test_given_workspace_with_git_repo_when_persisted_then_snapshot_contains_commit_sha`
     - `TestPersistWorkspaceState::test_given_workspace_with_uncommitted_changes_when_persisted_then_diff_captured`
     - `TestPersistWorkspaceState::test_given_workspace_with_progress_file_when_persisted_then_events_included`

3. **Add recover_session flow that restores into fresh container**
   - Add to `recovery.py`:
     - `recover_session(container_manager, session_manager, workspace_volume, feature_spec, last_checkpoint) -> tuple[ContainerHandle, SessionHandle]`: creates a fresh container with the same workspace volume, starts it, launches a new CC session with context from `last_checkpoint` (resume point, remaining spec items), and returns the new handles.
   - Add tests:
     - `TestRecoverSession::test_given_crashed_session_when_recovered_then_fresh_container_created`
     - `TestRecoverSession::test_given_crashed_session_when_recovered_then_workspace_volume_remounted`
     - `TestRecoverSession::test_given_crashed_session_when_recovered_then_cc_launched_with_resume_context`
     - `TestRecoverSession::test_given_resume_point_at_pr2_c1_when_recovered_then_cc_starts_from_pr2_c1`

---

### PR 6: Capability Spec, Handler Wiring & End-to-End Integration (Phase 6)

**Description**: Create the `coding.implement_feature_from_spec` capability spec, implement the `docker_worker_handler` that orchestrates the full Docker worker lifecycle behind the standard handler signature, wire it into the Archipelago pipeline, and run end-to-end integration tests.

**Acceptance Criteria Addressed**: #30, #31, #32, #33, #34, #35

**Complexity**: L

**Dependencies**: PR 1-5 (all prior phases provide the components composed here)

**Files created**:
- `src/archipelago/capabilities/coding_implement_feature_from_spec.yaml`
- `src/archipelago/docker_worker/handler.py`
- `tests/archipelago/test_docker_worker_capability_spec.py`
- `tests/archipelago/test_docker_worker_handler.py`
- `tests/archipelago/test_docker_worker_e2e.py`

**Files modified**:
- `src/archipelago/capabilities/dev_implement_feature_tdd.yaml` (add `deprecated: true` tag)
- `src/archipelago/archipelago_system.json` (update `dev_test` node to use `coding.implement_feature_from_spec`)
- `src/agent_foundry/planner/planner.py` (update `_ARCHIPELAGO_PIPELINE_PLAN` to reference new capability)

**Commits**:

1. **Add coding.implement_feature_from_spec capability spec YAML**
   - Create `src/archipelago/capabilities/coding_implement_feature_from_spec.yaml`:
     - `name: coding.implement_feature_from_spec`
     - `description: Delegates feature implementation to Claude Code running in an ephemeral Docker container with TDD workflow`
     - `version: "1.0.0"`
     - `implementation: {module: archipelago.docker_worker.handler, class_name: DockerWorkerHandler}`
     - `inputs_schema`: JSON Schema matching `WorkerInput.model_json_schema()`
     - `outputs_schema`: JSON Schema matching `WorkerResult.model_json_schema()`
     - `tags: [archipelago, docker-worker, coding, tdd, implementation]`
     - `quality_controls: {timeout_seconds: 7200, max_retries: 1}`
   - Update `src/archipelago/capabilities/dev_implement_feature_tdd.yaml`: add `deprecated` to tags list.
   - Create `tests/archipelago/test_docker_worker_capability_spec.py` with tests:
     - `TestCodingSpec::test_given_yaml_file_when_loaded_then_returns_valid_capability_spec`
     - `TestCodingSpec::test_given_coding_spec_when_inputs_schema_validates_worker_input_then_passes`
     - `TestCodingSpec::test_given_coding_spec_when_outputs_schema_validates_worker_result_then_passes`
     - `TestRegistryIntegration::test_given_registry_when_searched_by_docker_worker_tag_then_returns_coding_spec`

2. **Add docker_worker_handler composing all subsystems**
   - Create `src/archipelago/docker_worker/handler.py` with:
     - `docker_worker_handler(state: dict[str, Any]) -> dict[str, Any]`:
       1. Extracts `worker_input` from state, validates as `WorkerInput`.
       2. Creates `ContainerManager` with Docker client.
       3. Creates and starts container via `ContainerManager`.
       4. Launches PTY session via `SessionManager`.
       5. Registers output callback for log streaming.
       6. Registers `InterruptDetector` as an output callback.
       7. Waits for session to exit or interrupt.
       8. On interrupt: returns state with `breakpoint_payload` for pipeline pause.
       9. On exit: parses `progress.jsonl`, builds `WorkerResult`, tears down container.
       10. On error/timeout: persists workspace state, tears down, returns error result.
     - `DOCKER_WORKER_HANDLERS` dict: `{"coding.implement_feature_from_spec": docker_worker_handler}`.
   - Create `tests/archipelago/test_docker_worker_handler.py` with tests (all Docker interactions mocked):
     - `TestDockerWorkerHandler::test_given_valid_worker_input_when_called_then_container_created_and_started`
     - `TestDockerWorkerHandler::test_given_valid_worker_input_when_called_then_session_launched`
     - `TestDockerWorkerHandler::test_given_successful_cc_run_when_called_then_worker_result_returned`
     - `TestDockerWorkerHandler::test_given_successful_cc_run_when_called_then_worker_result_validates`
     - `TestDockerWorkerHandler::test_given_cc_timeout_when_called_then_status_is_timed_out`
     - `TestDockerWorkerHandler::test_given_cc_crash_when_called_then_workspace_state_persisted`
     - `TestDockerWorkerHandler::test_given_interrupt_during_run_when_called_then_breakpoint_payload_set`
     - `TestDockerWorkerHandler::test_given_handler_completes_when_called_then_container_destroyed`

3. **Update pipeline plan and planner to use new capability**
   - Update `src/archipelago/archipelago_system.json`: change `dev_test` node's `capability` from `dev_implement_feature_tdd` to `coding.implement_feature_from_spec`; update `capability_versions` accordingly.
   - Update `_ARCHIPELAGO_PIPELINE_PLAN` in `src/agent_foundry/planner/planner.py` to match.
   - Add tests to `tests/archipelago/test_docker_worker_handler.py`:
     - `TestPipelineIntegration::test_given_updated_plan_when_validated_then_all_7_checks_pass`
     - `TestPipelineIntegration::test_given_handler_registry_with_docker_worker_when_compile_plan_called_then_compiles`

4. **Add end-to-end integration tests with tracing**
   - Create `tests/archipelago/test_docker_worker_e2e.py` with tests (Docker mocked, full pipeline wired):
     - `TestEndToEnd::test_given_valid_input_when_pipeline_runs_then_final_state_has_worker_result`
     - `TestEndToEnd::test_given_valid_input_when_pipeline_runs_then_worker_result_validates`
     - `TestEndToEnd::test_given_pipeline_with_tracer_when_run_then_docker_worker_span_emitted`
     - `TestEndToEnd::test_given_pipeline_with_tracer_when_run_then_lifecycle_child_spans_emitted`
     - `TestEndToEnd::test_given_interrupt_during_pipeline_when_breakpoint_hit_then_state_contains_payload`
     - `TestEndToEnd::test_given_resumed_after_interrupt_when_pipeline_continues_then_completes`
   - Run all existing tests to confirm no regressions.

---

## Dependency Graph

```
PR 1 (Data Models & Progress Schema)
  |
  v
PR 2 (Container Lifecycle)
  |
  v
PR 3 (PTY Session & Streaming)
  |          \
  v           v
PR 4          PR 5
(Interrupts)  (Progress Parsing & Recovery)
  |           |
  v           v
  +-----+-----+
        |
        v
PR 6 (Capability Spec, Handler Wiring & E2E)
```

PR 4 and PR 5 are independent of each other and can be developed in parallel once PR 3 is merged. PR 6 composes all prior work and must wait for PRs 4 and 5.

---

## Implementation Notes

### Patterns to Follow

- **Capability spec YAML structure**: Follow the exact format of existing specs (e.g., `src/archipelago/capabilities/dev_implement_feature_tdd.yaml`). Fields: `name`, `description`, `version`, `implementation`, `inputs_schema`, `outputs_schema`, `tags`, `quality_controls`.
- **Handler function signature**: `def handler(state: dict[str, Any]) -> dict[str, Any]` -- takes full state, returns merged state. Follow `_retriever_handler` in `src/agent_foundry/demo/runner.py`.
- **Handler registry**: A plain `dict[str, Callable]` mapping capability names to handler functions. Follow `DEMO_HANDLERS` in `src/agent_foundry/demo/runner.py`.
- **Module structure**: New code goes under `src/archipelago/docker_worker/`. Submodules: `models.py`, `container.py`, `session.py`, `interrupts.py`, `progress.py`, `recovery.py`, `handler.py`.
- **Error classes**: Follow the pattern in `src/agent_foundry/compiler/errors.py` and `src/agent_foundry/registry/errors.py` -- typed exceptions with structured context fields.
- **Test structure**: Class-based grouping with descriptive Given/When/Then test names. Fixtures for shared setup (mocked Docker client, container handles). Follow `tests/test_compiler_basic.py`.

### Docker SDK Mocking Strategy for Tests

All unit tests must mock the Docker SDK (`docker.DockerClient`) to avoid requiring a running Docker daemon. Use `unittest.mock.patch` to replace `docker.from_env()` with a mock client. The mock should simulate:
- `client.containers.create()` returning a mock container with configurable attributes
- `container.start()`, `container.stop()`, `container.remove()` tracking call counts
- `container.exec_run()` returning mock exec results with configurable output
- `client.api.exec_create()` and `client.api.exec_start()` for PTY-based exec

Integration tests (marked `@pytest.mark.integration`) use a real Docker daemon and a lightweight test image. These are excluded from `pdm run pytest` by default; run with `pdm run pytest -m integration`.

### Safety Baseline Enforcement

The `ContainerManager.create_container()` method is the single enforcement point for all safety controls. Tests must verify each control individually:
- Non-root user: `user="1000:1000"`
- Capability drop: `cap_drop=["ALL"]`
- Read-only rootfs: `read_only=True`
- Writable workspace: bind mount with `mode="rw"` for workspace volume only
- Temp filesystem: `tmpfs={"/tmp": "size=256m"}`
- Resource limits: `mem_limit`, `cpu_quota`, `pids_limit` from `WorkerConstraints`
- Environment filtering: only variables in `env_allowlist` are passed
- No host mounts: validated by asserting no bind mounts other than the workspace volume

### Interrupt Protocol Wire Format

CC emits interrupt markers as single lines in stdout:
```
ARCHIPELAGO_NEED_CLARIFICATION {"question": "Which database driver?", "options": ["pg", "mysql"], "default": "pg", "blocking": true}
ARCHIPELAGO_NEED_PERMISSION {"action": "install npm package lodash", "risk_level": "low", "why_needed": "Required for data transformation", "alternatives": ["implement manually"]}
```

The `InterruptDetector` uses a regex pattern `^ARCHIPELAGO_NEED_(CLARIFICATION|PERMISSION)\s+(\{.*\})$` to match these lines. The JSON payload is parsed and validated against the corresponding Pydantic model. Malformed payloads are logged as warnings and treated as normal output (not interrupts).

### Risk Mitigations

- **Docker daemon unavailability**: All unit tests mock Docker SDK. Integration tests are opt-in via `@pytest.mark.integration`. The handler gracefully returns an error `WorkerResult` with `status="failed"` if Docker is unavailable.
- **PTY stream reliability**: The `SessionManager` uses a background thread for output consumption with a configurable read timeout. If the stream stalls beyond the timeout, the session is marked as `exited` with a timeout status.
- **Progress file corruption**: `parse_progress()` skips malformed JSON lines with a warning rather than failing the entire parse. The `get_resume_point()` function is conservative -- if it cannot determine a clean boundary, it returns the earliest incomplete commit.
- **Container resource leaks**: The `docker_worker_handler` uses a try/finally block to ensure `destroy()` is called. The `ContainerManager` also tracks all created containers and provides a `cleanup_all()` method for emergency cleanup.
- **Schema drift between models and YAML specs**: Each commit that adds or modifies a model includes a test verifying the model's `model_json_schema()` matches the YAML spec's schema. This catches drift immediately.
- **Existing test regressions**: Adding the new capability spec to `src/archipelago/capabilities/` increases the registry size. Any test asserting a specific registry size must be updated. The `dev_implement_feature_tdd` spec remains but is tagged `deprecated` so existing tag searches for `"archipelago"` will still include it (5 results instead of 4). Tests asserting `len == 4` for the `"archipelago"` tag must be updated to account for this.

---

## Post-Implementation Notes

### Adapter Protocol (implemented)

The adapter-orchestrator communication protocol was implemented across 4 PRs (see `adapter_protocol_spec.md`). Key files:

- `src/archipelago/docker_worker/protocol.py` — Pydantic message models, discriminated union parser
- `src/archipelago/docker_worker/ansi.py` — ANSI escape code stripping (PTY mode only)
- `src/archipelago/docker_worker/handler.py` — rewritten to use `_HandlerWSServer` + protocol messages
- `src/archipelago/docker_worker/container.py` — added `extra_env` parameter, removed `sleep infinity` override
- `lab/adapter.py` — PTY adapter with `run_protocol_adapter()`
- `lab/headless_adapter.py` — headless adapter using `claude -p --output-format stream-json`

### Headless Adapter Discovery

During prototyping, we discovered that Claude Code's `--output-format stream-json` with `-p` (headless mode) produces clean, structured JSON output — eliminating the need for PTY management, ANSI stripping, TUI noise filtering, trust confirmation, and ICRNL conversion. Multi-turn conversations work via `--resume SESSION_ID`.

The headless adapter (`lab/headless_adapter.py`) is ~150 lines vs ~400 for the PTY adapter. It uses `subprocess.Popen` instead of `pexpect`, reads JSON lines from stdout, and maps Claude Code's event types (`system`, `assistant`, `result`) to protocol messages.

### Task Completion Signaling

Two-layer design:

1. **Fast signal (adapter)**: Claude outputs `ARCHIPELAGO_TASK_COMPLETE` marker (instructed via CLAUDE.md). The adapter detects it and sends `status:completed`. The container stays alive.
2. **Safety net (gate node)**: A gate node after each dev node validates work against the spec, runs tests, checks gates. If the gate rejects, it resumes the same Claude session. If the gate accepts, it sends `control:terminate`.

**Failure mode analysis**:
- False complete (Claude wrong) → gate catches it, loops back to dev node. Cost: one gate evaluation.
- False turn_complete (marker missed) → delay until timeout or external signal. Cost: time.
- Correct complete → fast path through gate. Cost: none.

The adapter defaults to `turn_complete` (safe) and only sends `completed` when it detects the marker or receives `control:complete`.

### Prompt Injection Resistance

During testing, Claude Code was asked by a user to output the `ARCHIPELAGO_TASK_COMPLETE` marker. Claude refused, recognizing it as a protocol control signal that would falsely indicate task completion. It learned this from reading the adapter source code in its working directory. This is a desirable property: the marker is resistant to social engineering while being responsive to authoritative CLAUDE.md instructions.
