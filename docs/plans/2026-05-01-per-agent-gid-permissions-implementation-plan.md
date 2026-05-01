# Per-Agent GID Filesystem Permissions — Implementation Plan

> **Design:** `docs/design/2026-05-01-per-agent-gid-filesystem-permissions.md`
> **Branch:** `feat/per-agent-uid-permissions` (both repos)
> **For agents:** Use team-dev (parallel) or sdd (sequential) to implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the incorrect UID-based write-access model with Linux GID-based group permissions. Each `AgentAction` declares which GIDs its process should hold; Agent Foundry threads those GIDs into `docker exec --group-add` at invocation time. Write access is enforced by the kernel, not by application logic, so two containers may operate simultaneously on the same volume without race conditions.

**Architecture:** `AgentAction` drops `visible_dirs`, `writable_dirs`, and `uid`; gains `gids: list[int]`. `LiveContainer` gains `gids: list[int]`, populated from `primitive.gids`. `ContainerManager.exec_run` gains a `group_add: list[int]` parameter forwarded to the Docker SDK. `_run_claude_turn` passes `group_add=live.gids` when invoking Claude Code. Workspace bootstrap sets GID ownership on shared volume directories. Archipelago agent primitives declare their resource GIDs.

**What's on the branch already (partially wrong):**
- `lifecycle.py`: `user: str = _AGENT_USER` on `exec_run` — **correct, keep**. `user: str | None = None` on `create_container` — **wrong, revert**.
- `registry.py`: `str(primitive.uid)` wired to `create_container` — **wrong, revert**.
- `models.py`: `uid`, `visible_dirs`, `writable_dirs`, and uid validator — **wrong model design, replace with `gids`**.
- `fakes.py`: `user: str | None = None` on `create_container` — **wrong, revert**. `user` on `exec_run` — **keep structure, extend with `group_add`**.
- `test_agent_action_model.py`: `TestAgentActionUidValidation` (5 tests) — **obsolete, delete**.
- `test_uid_filesystem_permissions.py`: UID-based integration tests — **wrong mechanism, replace**.

**Tech Stack:** Python 3.14, Pydantic 2, Docker SDK (`docker` package), pytest with `integration` marker, `pdm test-all` / `pdm test-unit` / `pdm test-integration`. All agent-foundry work in `agent-foundry/`; Archipelago work in `archipelago/`.

---

## File Structure

### Agent Foundry

| File | Action | Responsibility |
|------|--------|----------------|
| `src/agent_foundry/primitives/models.py` | Modify | Remove `uid`, `visible_dirs`, `writable_dirs`, uid validator; add `gids: list[int]` |
| `src/agent_foundry/agents/lifecycle.py` | Modify | Revert `create_container` `user` param; add `group_add: list[int]` to `exec_run` |
| `src/agent_foundry/orchestration/registry.py` | Modify | Revert uid wiring from `create_container`; add `gids` to `LiveContainer`; populate from `primitive.gids` |
| `src/agent_foundry/orchestration/container_executor.py` | Modify | Pass `group_add=live.gids` to `exec_run` in `_run_claude_turn` |
| `tests/agent_foundry/orchestration/fakes.py` | Modify | Revert `create_container` `user` param; add `group_add` to `exec_run`; add `exec_calls` log |
| `tests/agent_foundry/primitives/test_agent_action_model.py` | Modify | Delete `TestAgentActionUidValidation`; remove `visible_dirs`/`writable_dirs` tests from `TestAgentActionConfigFields`; add `TestAgentActionGids` |
| `tests/agent_foundry/orchestration/test_registry.py` | Modify | Add `TestLiveContainerGids` and `TestGetOrCreateGids` test classes |
| `tests/agent_foundry/orchestration/test_container_executor.py` | Modify | Add `TestRunClaudeTurnGidThreading` test class |
| `tests/agent_foundry/integration/test_uid_filesystem_permissions.py` | Delete | Replaced by GID-based integration test |
| `tests/agent_foundry/integration/test_gid_filesystem_permissions.py` | Create | Docker integration tests — GID write enforcement + `tests/` override |

### Archipelago

| File | Action | Responsibility |
|------|--------|----------------|
| `src/archipelago/agents/designer/primitive.py` | Modify | Replace `uid=1001, visible_dirs=[...], writable_dirs=[...]` with `gids=[1001]` |
| `src/archipelago/agents/change_set_planner/primitive.py` | Modify | Replace `uid=1001, visible_dirs=[...], writable_dirs=[...]` with `gids=[1001]` |
| `src/archipelago/agents/tdd_planner/primitive.py` | Modify | Replace `uid=1001, visible_dirs=[...], writable_dirs=[...]` with `gids=[1001]` |
| `tests/archipelago/agents/designer/test_primitive.py` | Modify | Replace `test_given_designer_when_inspected_then_dir_policy_matches_design` with `test_given_designer_when_inspected_then_gids_are_documents_writer` |
| `tests/archipelago/agents/change_set_planner/__init__.py` | Create | Test-package marker |
| `tests/archipelago/agents/change_set_planner/test_primitive.py` | Create | Config assertions for change_set_planner primitive |
| `tests/archipelago/agents/tdd_planner/__init__.py` | Create | Test-package marker |
| `tests/archipelago/agents/tdd_planner/test_primitive.py` | Create | Config assertions for tdd_planner primitive |

---

## Dependency graph

```
Task A1 (revert lifecycle) ──┐
Task A2 (revert registry)    ├─▶ Task B1 (AgentAction.gids) ─▶ Task C1 (exec_run group_add)
Task A3 (revert fakes)   ────┘                                       │
                                                                      ▼
                                                              Task D1 (LiveContainer.gids)
                                                                      │
                                                                      ▼
                                                              Task E1 (_run_claude_turn)
                                                                      │
                                                              ┌───────┴────────┐
                                                              ▼                ▼
                                                        Task F1            Task G1
                                                      (integration)     (archipelago)
                                                              │
                                                              ▼
                                                         Task H1 (cleanup)
```

---

## Phase A — Prep: Revert incorrect changes

These reverts are not TDD (they restore correctness, not add behavior). Run the full test suite after each to confirm no regressions.

### Task A1: Revert `create_container` user param from lifecycle.py

**Files:** `src/agent_foundry/agents/lifecycle.py`

**Why:** Passing `--user` at `docker run` time breaks the entrypoint, which must run as root. GID enforcement is at `docker exec` time, not container creation time.

- [ ] **Step 1: Confirm current test suite baseline.**

  ```bash
  cd /home/markn/engineering/jig-archipelago/agent-foundry
  pdm test-unit
  ```

- [ ] **Step 2: Revert `user: str | None = None` from `ContainerManagerBase.create_container` signature.**

  Remove the `user` parameter from the abstract method signature in `ContainerManagerBase` (line ~145).

- [ ] **Step 3: Revert `user: str | None = None` from `ContainerManager.create_container` signature and implementation.**

  In `ContainerManager.create_container` (line ~232): remove the `user` parameter, remove the `if user is not None: create_kwargs["user"] = user` block, and restore the direct `self._client.containers.create(image, ...)` call without the `create_kwargs` dict (or keep `create_kwargs` but without the user handling).

- [ ] **Step 4: Run unit tests — confirm PASS.**

  ```bash
  pdm test-unit
  ```

---

### Task A2: Revert uid wiring from registry.py

**Files:** `src/agent_foundry/orchestration/registry.py`

**Why:** `primitive.uid` was incorrectly wired to `create_container`. The field is being removed; the wiring must go too.

- [ ] **Step 1: Remove the `str(primitive.uid) if primitive.uid is not None else None` line** from `get_or_create` (line ~153). Restore the original call shape without the user argument.

- [ ] **Step 2: Run unit tests — confirm PASS.**

  ```bash
  pdm test-unit
  ```

---

### Task A3: Revert `create_container` user param from fakes.py

**Files:** `tests/agent_foundry/orchestration/fakes.py`

**Why:** `FakeContainerManager` mirrors `ContainerManagerBase`. After Task A1 removes `user` from the abstract method, the fake must match.

- [ ] **Step 1: Remove `user: str | None = None` from `FakeContainerManager.create_container`.**

- [ ] **Step 2: Run unit tests — confirm PASS.**

  ```bash
  pdm test-unit
  ```

---

## Phase B — AgentAction.gids model

### Task B1: Replace uid/visible_dirs/writable_dirs with gids

**Files:**
- Modify: `tests/agent_foundry/primitives/test_agent_action_model.py`
- Modify: `src/agent_foundry/primitives/models.py`

**Dependencies:** Phase A complete.

- [ ] **Step 1 [RED]: Delete `TestAgentActionUidValidation` from test_agent_action_model.py.**

  Remove the entire `TestAgentActionUidValidation` class (5 tests). These test the wrong concept.

- [ ] **Step 2 [RED]: Remove visible_dirs / writable_dirs tests from `TestAgentActionConfigFields`.**

  Delete `test_visible_dirs_default_to_empty` and `test_writable_dirs_default_to_empty` from `TestAgentActionConfigFields`. The fields are going away.

- [ ] **Step 3 [RED]: Add `TestAgentActionGids` class to test_agent_action_model.py.**

  ```python
  class TestAgentActionGids:
      """AgentAction.gids declares which GIDs the agent process should hold."""

      def test_given_no_gids_when_created_then_defaults_to_empty_list(self):
          assert _new_structured_action().gids == []

      def test_given_gids_list_when_created_then_stored(self):
          action = AgentAction[StubInput, StubOutput](
              name="writer",
              prompt_builder=_stub_prompt_builder,
              instructions_provider=_stub_instructions_provider,
              executor=_stub_executor,
              reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
              gids=[1001, 1002],
          )
          assert action.gids == [1001, 1002]

      def test_given_empty_gids_when_created_then_valid_read_only_agent(self):
          action = AgentAction[StubInput, StubOutput](
              name="reader",
              prompt_builder=_stub_prompt_builder,
              instructions_provider=_stub_instructions_provider,
              executor=_stub_executor,
              reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
              gids=[],
          )
          assert action.gids == []

      def test_given_single_gid_when_created_then_accepted(self):
          action = AgentAction[StubInput, StubOutput](
              name="documents-writer",
              prompt_builder=_stub_prompt_builder,
              instructions_provider=_stub_instructions_provider,
              executor=_stub_executor,
              reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
              gids=[1001],
          )
          assert action.gids == [1001]
  ```

- [ ] **Step 4: Run unit tests — confirm FAIL (gids field does not exist yet).**

  ```bash
  pdm test-unit
  ```

  Expected: `TestAgentActionGids` tests fail with `ValidationError` or `AttributeError`. `TestAgentActionConfigFields` tests for `visible_dirs`/`writable_dirs` no longer exist (already deleted).

- [ ] **Step 5 [GREEN]: Update `AgentAction` in models.py.**

  - Remove `visible_dirs: list[str] = Field(default_factory=list)`
  - Remove `writable_dirs: list[str] = Field(default_factory=list)`
  - Remove `uid: int | None = Field(default=None)`
  - Remove the `_uid_required_when_writable` model_validator
  - Remove the `model_validator` import if it's now unused
  - Add `gids: list[int] = Field(default_factory=list)`
  - Update the comment block above the field to reflect the GID model:
    ```python
    # Filesystem access — GID-based group permissions.
    # Lists the supplementary GIDs the agent process should hold when
    # Claude Code is invoked via docker exec --group-add. An empty list
    # means no supplementary groups (read-only against group-owned dirs).
    # workspace_bootstrap is responsible for chown/chmod of workspace
    # directories to their respective GIDs before agents run.
    gids: list[int] = Field(default_factory=list)
    ```

- [ ] **Step 6: Run unit tests — confirm PASS.**

  ```bash
  pdm test-unit
  ```

---

## Phase C — exec_run group_add parameter

### Task C1: Add group_add to exec_run

**Files:**
- Modify: `tests/agent_foundry/orchestration/fakes.py`
- Modify: `src/agent_foundry/agents/lifecycle.py`

**Dependencies:** Task B1 complete.

- [ ] **Step 1 [RED]: Extend `FakeContainerManager` to record group_add and accept the parameter.**

  Add an `exec_calls: list[dict]` field to `FakeContainerManager` (alongside `exec_log`) and update `exec_run` to accept `group_add: list[int] = field(default_factory=list)` and record the call:

  ```python
  exec_calls: list[dict] = field(default_factory=list)

  def exec_run(
      self,
      handle: FakeContainerHandle,
      cmd: list[str],
      *,
      user: str = "claude",
      group_add: list[int] | None = None,
  ) -> ExecResult:
      self.exec_log.append(" ".join(cmd))
      self.exec_calls.append({"cmd": cmd, "user": user, "group_add": group_add or []})
      return self.exec_script.get(tuple(cmd), ExecResult(exit_code=0, output=b""))
  ```

  This does not break existing tests — `exec_log` still works; `exec_calls` provides richer introspection.

- [ ] **Step 2 [RED]: Add `TestExecRunGroupAdd` class to an appropriate test module.**

  Add to `tests/agent_foundry/orchestration/test_registry.py` (or a new `test_lifecycle.py`). Test that `FakeContainerManager.exec_run` records `group_add` correctly:

  ```python
  class TestFakeContainerManagerExecRunGroupAdd:
      def test_exec_run_records_group_add_kwarg(self):
          fake = FakeContainerManager()
          handle = fake.create_container("img")
          fake.exec_run(handle, ["echo", "hi"], group_add=[1001, 1002])
          assert fake.exec_calls[0]["group_add"] == [1001, 1002]

      def test_exec_run_defaults_group_add_to_empty(self):
          fake = FakeContainerManager()
          handle = fake.create_container("img")
          fake.exec_run(handle, ["echo", "hi"])
          assert fake.exec_calls[0]["group_add"] == []
  ```

- [ ] **Step 3: Run unit tests — confirm FAIL (`group_add` not yet accepted by abstract base).**

  ```bash
  pdm test-unit
  ```

- [ ] **Step 4 [GREEN]: Update `ContainerManagerBase.exec_run` abstract signature.**

  Add `group_add: list[int] | None = None` to the abstract method in `ContainerManagerBase`.

- [ ] **Step 5 [GREEN]: Update `ContainerManager.exec_run` concrete implementation.**

  ```python
  def exec_run(
      self,
      handle: ContainerHandle,
      cmd: list[str],
      *,
      user: str = _AGENT_USER,
      group_add: list[int] | None = None,
  ) -> ExecResult:
      """Run ``cmd`` inside the container as ``user`` with supplementary GIDs."""
      exit_code, output = handle._container.exec_run(
          cmd,
          demux=False,
          user=user,
          group_add=[str(g) for g in (group_add or [])],
      )
      return ExecResult(exit_code=exit_code, output=output)
  ```

- [ ] **Step 6: Run unit tests — confirm PASS.**

  ```bash
  pdm test-unit
  ```

---

## Phase D — LiveContainer.gids + registry wiring

### Task D1: Add gids to LiveContainer; populate from primitive.gids

**Files:**
- Modify: `tests/agent_foundry/orchestration/test_registry.py`
- Modify: `src/agent_foundry/orchestration/registry.py`

**Dependencies:** Task C1 complete.

- [ ] **Step 1 [RED]: Add `TestLiveContainerGids` to test_registry.py.**

  ```python
  class TestLiveContainerGids:
      def test_live_container_gids_defaults_to_empty(self):
          handle = FakeContainerHandle(container_id="c1", status="running")
          fake_mgr = FakeContainerManager()
          live = LiveContainer(handle=handle, manager=fake_mgr)
          assert live.gids == []

      def test_live_container_gids_accepts_list(self):
          handle = FakeContainerHandle(container_id="c1", status="running")
          fake_mgr = FakeContainerManager()
          live = LiveContainer(handle=handle, manager=fake_mgr, gids=[1001, 1002])
          assert live.gids == [1001, 1002]
  ```

- [ ] **Step 2 [RED]: Add `TestGetOrCreateGidPropagation` to test_registry.py.**

  Build on the existing `test_get_or_create_creates_exactly_one_container_on_first_call` fixture pattern:

  ```python
  class TestGetOrCreateGidPropagation:
      @pytest.mark.asyncio
      async def test_given_primitive_with_gids_when_get_or_create_then_live_container_gids_match(
          self, ...
      ):
          # Primitive with gids=[1001]
          # After get_or_create, live.gids == [1001]

      @pytest.mark.asyncio
      async def test_given_primitive_with_no_gids_when_get_or_create_then_live_container_gids_empty(
          self, ...
      ):
          # Primitive with gids=[]
          # After get_or_create, live.gids == []
  ```

- [ ] **Step 3: Run unit tests — confirm FAIL (`LiveContainer` has no `gids` field).**

  ```bash
  pdm test-unit
  ```

- [ ] **Step 4 [GREEN]: Add `gids: list[int]` field to `LiveContainer`.**

  ```python
  @dataclass
  class LiveContainer:
      handle: ContainerHandleBase
      manager: ContainerManagerBase
      session_id: str | None = None
      primitive_id: int | None = None
      agent_name: str | None = None
      gids: list[int] = field(default_factory=list)
      created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
      _invocation_count: int = 0
      ...
  ```

- [ ] **Step 5 [GREEN]: Populate `live.gids` from `primitive.gids` in `get_or_create`.**

  In `AgentContainerRegistry.get_or_create`, where `LiveContainer(...)` is constructed (line ~168):

  ```python
  live = LiveContainer(
      handle=handle,
      manager=self.manager,
      primitive_id=id(primitive),
      agent_name=agent_name,
      gids=primitive.gids,
  )
  ```

- [ ] **Step 6: Run unit tests — confirm PASS.**

  ```bash
  pdm test-unit
  ```

---

## Phase E — _run_claude_turn GID threading

### Task E1: Pass group_add=live.gids when invoking Claude Code

**Files:**
- Modify: `tests/agent_foundry/orchestration/test_container_executor.py`
- Modify: `src/agent_foundry/orchestration/container_executor.py`

**Dependencies:** Task D1 complete.

- [ ] **Step 1 [RED]: Add `TestRunClaudeTurnGidThreading` to test_container_executor.py.**

  The existing tests at line 550 use `_make_live_with_fake_mgr`. Extend the fixture pattern to include `gids`:

  ```python
  class TestRunClaudeTurnGidThreading:
      @pytest.mark.asyncio
      async def test_given_live_with_gids_when_turn_runs_then_exec_run_receives_group_add(self):
          # Build a live container with gids=[1001]
          # Run _run_claude_turn
          # Assert fake_mgr.exec_calls[0]["group_add"] == [1001]

      @pytest.mark.asyncio
      async def test_given_live_with_no_gids_when_turn_runs_then_exec_run_receives_empty_group_add(self):
          # Build a live container with gids=[]
          # Run _run_claude_turn
          # Assert fake_mgr.exec_calls[0]["group_add"] == []

      @pytest.mark.asyncio
      async def test_given_live_with_multiple_gids_when_turn_runs_then_all_gids_forwarded(self):
          # Build a live container with gids=[1001, 1002]
          # Assert fake_mgr.exec_calls[0]["group_add"] == [1001, 1002]
  ```

- [ ] **Step 2: Run unit tests — confirm FAIL (`_run_claude_turn` does not yet pass `group_add`).**

  ```bash
  pdm test-unit
  ```

- [ ] **Step 3 [GREEN]: Update `_run_claude_turn` in container_executor.py.**

  In `_do_exec` inside `_run_claude_turn`, change the `exec_run` call:

  ```python
  result = live.manager.exec_run(
      live.handle,
      cmd,
      user=str(1000),    # claude UID
      group_add=live.gids,
  )
  ```

  The `user` is the `claude` user's UID (1000). The constant `_AGENT_USER` in lifecycle.py is `"claude"` (a name, not a numeric UID). For `docker exec`, both the name and the numeric UID work; use the name for consistency with the existing `_AGENT_USER` constant unless the Docker SDK requires numeric. Check the existing `_AGENT_USER` value and use it:

  ```python
  from agent_foundry.agents.lifecycle import _AGENT_USER

  result = live.manager.exec_run(
      live.handle,
      cmd,
      user=_AGENT_USER,
      group_add=live.gids,
  )
  ```

- [ ] **Step 4: Run unit tests — confirm PASS.**

  ```bash
  pdm test-unit
  ```

- [ ] **Step 5: Run full test suite.**

  ```bash
  pdm test-all
  ```

  Integration tests that need Docker may skip — that is acceptable.

---

## Phase F — Integration tests: Docker GID enforcement

### Task F1: Rewrite integration test as GID-based

**Files:**
- Delete: `tests/agent_foundry/integration/test_uid_filesystem_permissions.py`
- Create: `tests/agent_foundry/integration/test_gid_filesystem_permissions.py`

**Dependencies:** Phase E complete (exec_run has group_add; `_run_claude_turn` threads gids).

**Notes:** These tests use the Docker SDK directly against an Alpine container and a named volume. They do not require the agent-worker image. They skip when the Docker daemon is unavailable. Each test class is independent — they do not share volume fixtures.

The key difference from the old UID-based tests: instead of creating a container with `user=str(uid)` (which affected the whole container), these tests use `container.exec_run(..., user="1000", group_add=["1001"])` to simulate what `_run_claude_turn` does.

- [ ] **Step 1: Delete `test_uid_filesystem_permissions.py`.**

  This file tests UID-based ownership, which is the wrong mechanism. It will be replaced in Step 2.

- [ ] **Step 2 [RED/GREEN]: Create `test_gid_filesystem_permissions.py`.**

  ```python
  """Integration tests — GID-based filesystem permission enforcement.

  Verifies that Linux group ownership + mode 775 correctly enforces read/write
  access when processes run with different supplementary GIDs:

    (1) A process with the matching GID can write to a GID-owned (mode 775) dir.
    (2) A process without the GID cannot write (falls to "others" r-x bits).
    (3) The tests/ override: a parent dir owned by GID 1002 (mode 775) with a
        subdirectory overridden to GID 1003 — a process holding GID 1002 but
        not GID 1003 cannot write to the subdirectory.

  Uses alpine (not agent-worker) — these tests exercise OS-level enforcement
  and require no Claude Code tooling. Skipped when Docker daemon unavailable.

  The exec helper mirrors what _run_claude_turn does: container runs as root
  initially, exec drops to a specific user with supplementary groups via
  docker exec --user / --group-add.
  """

  from __future__ import annotations

  import contextlib
  import uuid

  import pytest

  pytestmark = pytest.mark.integration

  ALPINE_IMAGE = "alpine:latest"
  GID_DOCUMENTS = 1001
  GID_CODEBASE = 1002
  GID_TESTS = 1003
  AGENT_UID = 1000     # "claude" user's UID in agent-worker; numeric for exec


  @pytest.fixture(scope="module")
  def docker_client():
      try:
          import docker
          client = docker.from_env()
          client.ping()
      except Exception as e:
          pytest.skip(f"docker daemon unavailable: {e}")
      return client


  @pytest.fixture
  def gid_workspace(docker_client):
      """Volume with GID-owned workspace directories.

      /workspace/documents  — owned by GID_DOCUMENTS, mode 775
      /workspace/codebase   — owned by GID_CODEBASE, mode 775
      /workspace/codebase/tests — owned by GID_TESTS, mode 775 (override)
      """
      import docker

      volume_name = f"gid-perm-test-{uuid.uuid4().hex[:8]}"
      docker_client.volumes.create(volume_name)
      try:
          docker_client.containers.run(
              ALPINE_IMAGE,
              remove=True,
              volumes={volume_name: {"bind": "/workspace", "mode": "rw"}},
              command=["sh", "-c", (
                  f"mkdir -p /workspace/documents /workspace/codebase/tests "
                  f"&& chown -R root:{GID_DOCUMENTS} /workspace/documents "
                  f"&& chmod -R 775 /workspace/documents "
                  f"&& chown -R root:{GID_CODEBASE} /workspace/codebase "
                  f"&& chmod -R 775 /workspace/codebase "
                  f"&& chown -R root:{GID_TESTS} /workspace/codebase/tests "
                  f"&& chmod -R 775 /workspace/codebase/tests"
              )],
          )
          yield volume_name
      finally:
          with contextlib.suppress(Exception):
              docker_client.volumes.get(volume_name).remove(force=True)


  def _exec_with_groups(
      docker_client, volume_name: str, uid: int, gids: list[int], cmd: str
  ) -> tuple[int, str]:
      """Run cmd inside a fresh alpine container as uid with supplementary gids.

      Mirrors what _run_claude_turn does: the container starts normally (as
      root), then exec drops to uid with group_add=gids — the same flow as
      the entrypoint running as root then exec_run invoking claude as claude.
      """
      container = docker_client.containers.create(
          ALPINE_IMAGE,
          command=["tail", "-f", "/dev/null"],
          volumes={volume_name: {"bind": "/workspace", "mode": "rw"}},
      )
      container.start()
      try:
          result = container.exec_run(
              ["sh", "-c", cmd],
              user=str(uid),
              group_add=[str(g) for g in gids],
          )
          return result.exit_code, result.output.decode(errors="replace")
      finally:
          container.remove(force=True)


  class TestGidWriteAccess:
      """A process with the matching GID can write; without it, cannot."""

      def test_given_documents_gid_when_writing_to_documents_dir_then_succeeds(
          self, docker_client, gid_workspace
      ):
          code, out = _exec_with_groups(
              docker_client, gid_workspace, AGENT_UID, [GID_DOCUMENTS],
              "touch /workspace/documents/test.txt"
          )
          assert code == 0, f"expected write success; got exit={code} output={out!r}"

      def test_given_no_matching_gid_when_writing_to_documents_dir_then_fails(
          self, docker_client, gid_workspace
      ):
          code, _ = _exec_with_groups(
              docker_client, gid_workspace, AGENT_UID, [],
              "touch /workspace/documents/test.txt"
          )
          assert code != 0

      def test_given_codebase_gid_when_writing_to_codebase_dir_then_succeeds(
          self, docker_client, gid_workspace
      ):
          code, out = _exec_with_groups(
              docker_client, gid_workspace, AGENT_UID, [GID_CODEBASE],
              "touch /workspace/codebase/impl.py"
          )
          assert code == 0, f"expected write success; got exit={code} output={out!r}"

      def test_given_no_gids_when_reading_any_dir_then_succeeds(
          self, docker_client, gid_workspace
      ):
          code, _ = _exec_with_groups(
              docker_client, gid_workspace, AGENT_UID, [],
              "ls /workspace/documents && ls /workspace/codebase"
          )
          assert code == 0


  class TestTestsDirGidOverride:
      """GID_CODEBASE members cannot write to tests/ (owned by GID_TESTS).

      The override: codebase/ is owned by GID_CODEBASE (mode 775), but
      codebase/tests/ is owned by GID_TESTS (mode 775). A process holding
      GID_CODEBASE but not GID_TESTS falls to "others" bits (r-x) on tests/.
      """

      def test_given_codebase_gid_when_writing_to_tests_subdir_then_fails(
          self, docker_client, gid_workspace
      ):
          code, _ = _exec_with_groups(
              docker_client, gid_workspace, AGENT_UID, [GID_CODEBASE],
              "touch /workspace/codebase/tests/test_foo.py"
          )
          assert code != 0

      def test_given_tests_gid_when_writing_to_tests_subdir_then_succeeds(
          self, docker_client, gid_workspace
      ):
          code, out = _exec_with_groups(
              docker_client, gid_workspace, AGENT_UID, [GID_TESTS],
              "touch /workspace/codebase/tests/test_foo.py"
          )
          assert code == 0, f"expected write success; got exit={code} output={out!r}"

      def test_given_codebase_gid_when_reading_tests_subdir_then_succeeds(
          self, docker_client, gid_workspace
      ):
          code, _ = _exec_with_groups(
              docker_client, gid_workspace, AGENT_UID, [GID_CODEBASE],
              "ls /workspace/codebase/tests"
          )
          assert code == 0

      def test_given_both_gids_when_writing_to_tests_subdir_then_succeeds(
          self, docker_client, gid_workspace
      ):
          """An agent holding both GIDs can write anywhere — multi-resource access."""
          code, out = _exec_with_groups(
              docker_client, gid_workspace, AGENT_UID, [GID_CODEBASE, GID_TESTS],
              "touch /workspace/codebase/impl.py && touch /workspace/codebase/tests/test_foo.py"
          )
          assert code == 0, f"expected both writes to succeed; got exit={code} output={out!r}"
  ```

- [ ] **Step 3: Run integration tests against a live Docker daemon — confirm PASS.**

  ```bash
  pdm test-integration
  ```

  If any test fails, the setup steps (chown/chmod ordering) may need adjustment. The `tests/` override depends on the two `chown` calls running in the correct order (codebase first, then tests/).

---

## Phase G — Archipelago: agent primitive updates

### Task G1: Replace uid/visible_dirs/writable_dirs with gids in agent primitives

**Files (Archipelago repo):**
- Modify: `tests/archipelago/agents/designer/test_primitive.py`
- Create: `tests/archipelago/agents/change_set_planner/__init__.py`
- Create: `tests/archipelago/agents/change_set_planner/test_primitive.py`
- Create: `tests/archipelago/agents/tdd_planner/__init__.py`
- Create: `tests/archipelago/agents/tdd_planner/test_primitive.py`
- Modify: `src/archipelago/agents/designer/primitive.py`
- Modify: `src/archipelago/agents/change_set_planner/primitive.py`
- Modify: `src/archipelago/agents/tdd_planner/primitive.py`

**Dependencies:** Phase E complete (gids field exists on AgentAction).

- [ ] **Step 1 [RED]: Update designer/test_primitive.py.**

  Replace `test_given_designer_when_inspected_then_dir_policy_matches_design`:

  ```python
  def test_given_designer_when_inspected_then_gids_are_documents_writer(self):
      assert designer.gids == [1001]
  ```

  Remove any references to `visible_dirs` or `writable_dirs`.

- [ ] **Step 2 [RED]: Create change_set_planner/test_primitive.py.**

  ```python
  from agent_foundry.orchestration.container_executor import run_agent_in_container
  from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy
  from archipelago.agents.change_set_planner.primitive import change_set_planner


  class TestChangeSetPlannerPrimitiveConfig:
      def test_is_agent_action(self):
          assert isinstance(change_set_planner, AgentAction)

      def test_name_is_change_set_planner(self):
          assert change_set_planner.name == "change_set_planner"

      def test_executor_is_run_agent_in_container(self):
          assert change_set_planner.executor is run_agent_in_container

      def test_reuse_policy_is_new_session(self):
          assert change_set_planner.reuse_policy is ContainerReusePolicy.REUSE_NEW_SESSION

      def test_timeout_is_30_minutes(self):
          assert change_set_planner.timeout_seconds == 1800

      def test_gids_are_documents_writer(self):
          assert change_set_planner.gids == [1001]
  ```

- [ ] **Step 3 [RED]: Create tdd_planner/test_primitive.py (same pattern as change_set_planner).**

- [ ] **Step 4: Run unit tests in archipelago — confirm FAIL.**

  ```bash
  cd /home/markn/engineering/jig-archipelago/archipelago
  pdm test-unit
  ```

- [ ] **Step 5 [GREEN]: Update designer/primitive.py.**

  Remove `visible_dirs=["/workspace"]`, `writable_dirs=["/workspace/documents"]`, `uid=1001`.
  Add `gids=[1001]`.

- [ ] **Step 6 [GREEN]: Update change_set_planner/primitive.py.**

  Same change: remove `visible_dirs`, `writable_dirs`, `uid`; add `gids=[1001]`.

- [ ] **Step 7 [GREEN]: Update tdd_planner/primitive.py.**

  Same change.

- [ ] **Step 8: Run unit tests in archipelago — confirm PASS.**

  ```bash
  pdm test-unit
  ```

- [ ] **Step 9: Run full suite in archipelago.**

  ```bash
  pdm test-all
  ```

---

## Phase H — Cleanup: Remove obsolete tests

### Task H1: Delete stale tests that no longer have a subject

**Dependencies:** All prior phases complete and passing.

This task removes tests whose subjects no longer exist. All deletions were anticipated by the RED steps in earlier phases; this task makes the cleanup explicit and ensures nothing slipped through.

- [ ] **Step 1: Confirm the full test suite is green before any deletions.**

  In agent-foundry:
  ```bash
  pdm test-all
  ```
  In archipelago:
  ```bash
  pdm test-all
  ```

- [ ] **Step 2: Verify `test_uid_filesystem_permissions.py` was deleted in Phase F.**

  ```bash
  ls tests/agent_foundry/integration/test_uid_filesystem_permissions.py
  ```
  Expected: file not found (was deleted in Task F1 Step 1).

- [ ] **Step 3: Verify `TestAgentActionUidValidation` is gone from test_agent_action_model.py.**

  ```bash
  grep -n "TestAgentActionUidValidation\|visible_dirs_default\|writable_dirs_default" \
    tests/agent_foundry/primitives/test_agent_action_model.py
  ```
  Expected: no matches.

- [ ] **Step 4: Verify `test_given_designer_when_inspected_then_dir_policy_matches_design` is gone.**

  ```bash
  grep -n "dir_policy_matches_design\|visible_dirs\|writable_dirs" \
    /home/markn/engineering/jig-archipelago/archipelago/tests/archipelago/agents/designer/test_primitive.py
  ```
  Expected: no matches.

- [ ] **Step 5: Run the full suite one final time — confirm clean.**

  In agent-foundry:
  ```bash
  pdm test-all
  ```
  In archipelago:
  ```bash
  pdm test-all
  ```

  Expected: all unit tests pass; integration tests pass if Docker is available, skip gracefully if not.
