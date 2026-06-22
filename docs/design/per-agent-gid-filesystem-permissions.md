# Per-Agent GID-Based Filesystem Permissions

> **Status:** Approved, 2026-05-01.
> **Branch:** `feat/per-agent-uid-permissions` (both repos)
> **Scope:** Agent Foundry platform + Archipelago workspace setup

## 1. Problem

Archipelago agents share a single Docker named volume (`/workspace`). Different agents need different write access to different directories on that volume simultaneously:

- The Test Agent must write `codebase/tests/` but not `codebase/` (outside tests).
- The Implementer must write `codebase/` but not `codebase/tests/`.
- Reasoning agents (Designer, Change Set Planner, TDD Planner) must write `documents/` but not `codebase/`.

Two concrete failure modes without enforcement:

1. **Unintended writes.** An agent writes to a directory it should not, corrupting another agent's work or bypassing the TDD discipline.
2. **Race condition.** If write access is managed by runtime configuration (e.g., application-level settings updated before each container run), two simultaneously running containers can observe each other's mutations to that configuration, giving one agent the wrong access level.

Agent Foundry must provide a mechanism that is:
- Enforced at the filesystem level, not in application logic.
- Per-process, not per-container (so the same Docker image serves every agent role).
- Race-condition-free when two containers operate simultaneously on the same volume.
- Requires no runtime reconfiguration of the volume.

## 2. Rejected Approaches

### 2.1 Claude Code permission settings (`allowedDirectories`)

Claude Code's built-in file tools (Read, Edit, Write) use its permission system directly. Bash subprocesses do not. The sandbox can restrict Bash, but Docker weakens sandbox guarantees for containerized agents. Neither mechanism is reliable enforcement against a determined or malfunctioning agent — both are best-effort.

More importantly: `allowedDirectories` is not a valid Claude Code setting. Even if similar settings existed and were reliable, they live inside the agent process and can be bypassed by Bash.

**Verdict:** Not filesystem enforcement. Rejected.

### 2.2 Docker mount mode (`ro`/`rw`)

Docker allows a named volume to be mounted read-only or read-write at container creation time. However, the mode applies to the **entire mount point** — it is not possible to mount the same volume as read-write at one path and read-only at a subdirectory. Per-directory, per-agent write control cannot be expressed this way.

**Verdict:** Wrong granularity. Rejected.

### 2.3 UID-based ownership (one UID per directory)

A natural extension of `--user` at container creation: assign each agent a distinct UID and `chown` each workspace directory to the agent that should write it. Directories are mode 755; non-owning processes fall to "others" bits (r-x) — read-only.

This works for single-directory access. It breaks when an agent needs write access to multiple directories (e.g., if a future agent role must write both `documents/` and `codebase/`) — a process can only have one UID.

There is also a structural constraint in Agent Foundry: the agent-worker container entrypoint runs as **root** to perform git credential setup, filesystem lockdown, and role-instruction injection before dropping to the `claude` user via `gosu`. Passing `--user` at `docker run` time would break the entrypoint. Enforcement must happen at `docker exec` time (when Claude Code is invoked), not at container creation time.

**Verdict:** Wrong Linux construct. UIDs are for identity; GIDs are for resource access. Rejected.

## 3. Approved Approach: Linux Group-Based Access Control

### 3.1 Core model

Linux groups (GIDs) model resource ownership. The correct mapping:

- **UID** — identifies *who the process is* (agent identity). Fixed: `claude` user, UID 1000.
- **GID** — identifies *which resources the process may access*. Variable: each agent is granted the supplementary GIDs for the directories it may write.

A directory owned by GID G with mode `775` (`rwxrwxr-x`) grants:
- **Group members** (processes with GID G as supplementary group): read + write + execute.
- **Others** (processes without GID G): read + execute only (no write).

Multiple supplementary GIDs can be added to a single process at `docker exec` time via `--group-add`. An agent that needs write access to two directories simply holds both GIDs.

### 3.2 Entrypoint constraint

The agent-worker entrypoint runs as root. `--user` at `docker run` time would prevent the entrypoint from completing. GID assignment must happen at `docker exec` time — when the host invokes Claude Code inside the container via `exec_run`. The `docker exec` API accepts `--group-add` independently of the container's startup user.

### 3.3 The `tests/` override

Archipelago requires that the Implementer can write `codebase/` but not `codebase/tests/`, while the Test Agent can write `codebase/tests/` but not the rest of `codebase/`.

This is achieved by setting the subdirectory to a different GID after setting the parent:

```
chown -R root:1002 /workspace/codebase    # GID 1002 owns all of codebase/
chmod -R 775       /workspace/codebase
chown -R root:1003 /workspace/codebase/tests  # GID 1003 overrides ownership of tests/
chmod -R 775       /workspace/codebase/tests
```

A process holding GID 1002 but not GID 1003 hits the "others" bits (`r-x`) on `codebase/tests/` — read-only, enforced by the kernel. No application logic required.

### 3.4 Race-condition safety

GID-based permissions are static filesystem state set once at workspace bootstrap. They do not change at runtime. Two containers running simultaneously read the same kernel-enforced permissions; there is no mutable runtime configuration to race on.

## 4. Agent Foundry Platform Changes

### 4.1 `AgentAction` model (`constructs/models.py`)

Remove `visible_dirs`, `writable_dirs`, and `uid`. Replace with:

```python
gids: list[int] = Field(default_factory=list)
```

`gids` is the list of supplementary GIDs the agent process should hold when Claude Code is invoked. An empty list means the agent's process has no supplementary GIDs — it falls to "others" bits on all group-owned directories (read-only for mode 775 dirs, no access for mode 770 dirs).

No validator is needed. An agent with no GIDs is a valid read-only agent; the semantics are consistent regardless of whether `gids` is empty or populated.

### 4.2 `LiveContainer` (`orchestration/registry.py`)

Add a `gids: list[int]` field to `LiveContainer` (the runtime handle for a running container). Populate it from `construct.gids` in `get_or_create` (or equivalent). The container itself is created without a `--user` override — the entrypoint runs as root as designed.

### 4.3 `exec_run` signature (`agents/lifecycle.py`)

Extend `ContainerManagerBase.exec_run` and `ContainerManager.exec_run` to accept:

```python
group_add: list[int] = field(default_factory=list)
```

Pass to the Docker SDK:

```python
handle._container.exec_run(
    cmd,
    demux=False,
    user=user,           # "1000" (claude user)
    group_add=[str(g) for g in group_add],
)
```

The `user` parameter (already added as `_AGENT_USER = "claude"`) is correct and stays. The `create_container` `user` parameter is incorrect (breaks the entrypoint) and must be reverted.

### 4.4 `_run_claude_turn` (`orchestration/container_executor.py`)

When invoking Claude Code via `exec_run`, pass:

```python
user=str(_AGENT_UID),   # 1000
group_add=live.gids,
```

This is the single point where agent identity and resource access are combined at invocation time.

## 5. Archipelago Consumer Changes

### 5.1 GID map

Three GIDs control write access to the three Archipelago workspace directories:

| GID  | Resource             | Directory                     | Agents                                      |
|------|----------------------|-------------------------------|---------------------------------------------|
| 1001 | `documents`          | `/workspace/documents`        | Designer, Change Set Planner, TDD Planner   |
| 1002 | `codebase`           | `/workspace/codebase`         | Implementer                                 |
| 1003 | `tests`              | `/workspace/codebase/tests`   | Test Agent                                  |

These GIDs must be defined in the agent-worker Docker image (in `/etc/group` or equivalent). They are burned into the image, not created per-container. Group names are optional but aid readability in shell debugging: `documents`, `codebase`, `tests`.

### 5.2 `workspace_bootstrap.py` — GID permission setup

Add a `setup_workspace_gid_permissions` function that runs a throwaway root container against the shared volume, executing:

```sh
chown -R root:1001 /workspace/documents
chmod -R 775       /workspace/documents
chown -R root:1002 /workspace/codebase
chmod -R 775       /workspace/codebase
chown -R root:1003 /workspace/codebase/tests
chmod -R 775       /workspace/codebase/tests
```

The `tests/` step must run after the `codebase/` step. The ordering is load-bearing: `codebase/tests` inherits GID 1002 from the `codebase/` chown, then the second `chown` overrides it to 1003. Reversing the order would set `tests/` to GID 1002 (no override).

### 5.3 Agent constructs (`designer`, `change_set_planner`, `tdd_planner`)

Replace `uid=1001, visible_dirs=[...], writable_dirs=[...]` with:

```python
gids=[1001],
```

The Implementer (not yet declared) will use `gids=[1002]`. The Test Agent will use `gids=[1003]`.

## 6. Test Strategy

### Unit tests — `test_agent_action_model.py`

- `gids` defaults to `[]`.
- `gids` accepts a non-empty list of ints.
- An agent with `gids=[]` is valid (read-only; no validator error).

### Integration tests — `test_uid_filesystem_permissions.py`

Tests use a lightweight Alpine image (not agent-worker) against an ephemeral Docker volume. Three test cases:

1. **`TestGidWriteAccess`**: a process invoked with `--group-add <gid>` can write to a directory owned by that GID (mode 775).
2. **`TestGidNoAccess`**: a process invoked without that GID cannot write to the same directory (exit code non-zero).
3. **`TestTestsDirOverride`**: a process with GID 1002 cannot write to a nested directory whose ownership was overridden to GID 1003.

These are integration tests and require a Docker daemon. They skip gracefully when one is unavailable.

## 7. What Does Not Change

- Container creation (`docker run`) — no `--user` override; entrypoint continues to run as root.
- The entrypoint itself — auth, git credentials, lockdown, role-instructions append, LSP plugin install all proceed as before.
- Agent-worker image UID layout — `claude` user remains UID 1000, GID 1000.
- `FunctionAction` and `Sequence` constructs — no `gids` field; these do not invoke Claude Code in a container.

## 8. Open Questions

- **Agent-worker image build**: GID definitions (`/etc/group` entries for 1001, 1002, 1003) need to be added to the Dockerfile. The exact diff is not in scope for this design document; it belongs in the implementation PR.
- **Future agents with multi-resource write**: An agent that needs write access to both `documents/` and `codebase/` would declare `gids=[1001, 1002]`. The mechanism supports this without changes; it is not needed for the current agent roster.
