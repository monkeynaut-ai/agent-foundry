# Project Check — 2026-04-29T22:18

Scope: full pass over `src/agent_foundry/`, `src/archetype/`, and the matching
`tests/` tree. Findings are anchored to file paths and line numbers verified
against the current branch; navigation was done with LSP/grep so each citation
should resolve with `goToDefinition`.

---

## 1. Three most egregious design problems

### D1. `container_executor` reaches around `ContainerManagerBase` to drive Docker directly

**Where.**
- `src/agent_foundry/orchestration/container_executor.py:142` —
  `live.handle._container.exec_run(cmd, demux=False, user="claude")`
- Same file lines 144, 187, 236, 251 — `.logs(...)`, `.reload`, etc.
- `src/agent_foundry/orchestration/container_executor.py:391-392` —
  `live._invocation_count = invocation` (mutates a private dataclass field).
- `src/agent_foundry/agents/recovery.py:96, 99` — same pattern.
- `src/agent_foundry/agents/lifecycle.py:59` — `_container: Any = field(...)`
  documented as an "Any-typed escape hatch", which the executor consumes as a
  primary API.

**Why this is poor design.**
The `ContainerManagerBase` ABC in `lifecycle.py:69-111` declares
`create_container`, `start`, `stop`, `destroy`, `read_file_from_container`,
`copy_from_container`, `write_file_to_container` — but **no `exec_run`**. The
single most important call in the runtime — running `claude` inside the
container, once per turn — has no place in the abstraction, so production
code reaches through `handle._container` straight to the docker SDK.

Consequences:
- Test fakes (`tests/agent_foundry/orchestration/fakes.py`) must mimic the
  Docker SDK shape and add their own `exec_run` (line 103) that has no
  counterpart on the abstract base, so the abstraction does not prevent
  accidental drift between fake and real.
- Every place that consumes `LiveContainer` is coupled to the docker-py
  Container surface; replacing the executor with an SDK or API path (called
  out as a future direction in `CLAUDE.md`'s "Platform Principles") cannot
  reuse `LiveContainer` as-is.
- The `_invocation_count` field is private (leading `_`) but mutated from
  outside the dataclass, so encapsulation is fictitious.

**How to improve.**
1. Add `exec_run(handle, cmd: list[str], *, user: str | None) -> ExecResult`
   to `ContainerManagerBase`, where `ExecResult` is a Pydantic model with
   `exit_code: int`, `stdout: bytes`, `stderr: bytes`. Move the
   `live.handle._container.exec_run` and `.logs` calls behind it.
2. Make `_container: Any` strictly internal to `ContainerManager` (drop it
   from the dataclass; let the manager keep its own `dict[str, ContainerObj]`
   keyed by handle id). External code never sees the docker-py object.
3. Replace `live._invocation_count = invocation` with a typed
   `LiveContainer.next_invocation()` method on the dataclass, or move the
   counter to the registry where invocation lifecycle already lives.

---

### D2. Typed Claude-event parser exists but the runtime uses raw dict access

**Where.**
- `src/agent_foundry/agents/claude_code_events.py:22-111` defines
  `SystemInitEvent`, `AssistantEvent`, `ResultEvent`, `ErrorEvent`,
  `parse_stream_event`, plus a tagged `ClaudeStreamEvent` union and the
  constants `STRUCTURED_OUTPUT_TOOL_NAME` and `NON_RECOVERABLE_STOP_REASONS`.
- `src/agent_foundry/orchestration/container_executor.py:153-194` parses the
  same stream by hand using `evt.get("type")`, `block.get("name")`,
  `block.get("input")`, and a regex fallback for ` ```json ` blocks.

**Why this is poor design.**
`CLAUDE.md` (project root) lists "Strict typing at all boundaries" as a
platform principle and explicitly states "Public APIs accept and return
Pydantic models, never raw dicts." The boundary between the orchestrator
and the Claude Code stream is exactly such a public API. A typed parser
already exists and is fully tested
(`tests/agent_foundry/agents/test_claude_code_events.py`), but the production
parse path bypasses it. The two implementations now drift independently:

- The typed model defines `STRUCTURED_OUTPUT_TOOL_NAME = "StructuredOutput"`;
  the executor uses the literal string at line 165.
- The typed model encodes `NON_RECOVERABLE_STOP_REASONS = frozenset({"refusal",
  "max_tokens"})`; the executor never consults this — a refusal stop is
  treated as a generic "no envelope" failure.
- The typed `ResultEvent` exposes `structured_output: dict | None`; the
  executor does not look at the result event at all, missing a path where
  Claude returns the structured payload via `result` rather than tool_use.

**How to improve.**
1. In `_run_claude_turn`, replace `for raw_line in output.decode().splitlines()`
   with a loop that calls `parse_stream_event(json.loads(line))` and then
   `match`-dispatches on the event type. Use the typed accessors
   (`evt.message.content`, `block.name == STRUCTURED_OUTPUT_TOOL_NAME`).
2. Have the parser carry its own state across lines (init → assistant
   blocks → optional result), returning a typed `TurnRawResult` that is
   then validated against `AgentTurnEnvelope[O]`.
3. If keeping the `tool_use` and `text` fallback-block paths, the typed
   model already discriminates them — drop the regex extraction and let the
   model do that work.

---

### D3. `PrimitivePlan._walk` uses an `isinstance` chain — extension point lost

**Where.**
- `src/agent_foundry/primitives/plan.py:33-45`:
  ```python
  if isinstance(prim, Sequence):
      for step in prim.steps: …
  elif isinstance(prim, (Loop, Retry)):
      result.extend(self._walk(prim.body))
  elif isinstance(prim, Conditional):
      …
  ```

**Why this is poor design.**
`CLAUDE.md` states "The compiler dispatches to per-type compiler functions
via a registry, not isinstance chains. The validator does the same. New
primitive types register their own compiler and validator without modifying
core code." `register_compiler` and `register_validator` are real and used
elsewhere — but `PrimitivePlan._walk()` is a hand-rolled type ladder that
products cannot extend without editing core code.

This silently breaks any product-defined primitive that has children
(`primitives.all_primitives()` will skip the children even if a compiler
and validator are properly registered for the new type). Every consumer
of `all_primitives()` — visualization, analysis, future static checks —
silently underreports.

**How to improve.**
1. Introduce a third per-primitive function: `children(prim) -> Iterable[Primitive]`,
   registered alongside the compiler and validator.
2. Make `_walk` look up the children function via the registry; raise on
   unregistered types just like the compiler and validator do.
3. Register the four built-in walkers (`_seq_children`, `_loop_children`,
   `_retry_children`, `_conditional_children`) at module import.

---

## 2. Test analysis

### T1. The `summary.py` tests codify the bug they should catch

`src/agent_foundry/orchestration/summary.py:110, 120` reads
`record.get("agent")`, but every emitter in the codebase uses `agent_name`
(see `container_executor.py:385, 396, 413, …`, `registry.py:157, 162`).

`tests/agent_foundry/orchestration/test_summary.py:36-47` constructs the
fixture jsonl with `"agent": agent` — i.e., the *fixture* uses the wrong key
to match the buggy reader. Tests pass because the synthetic jsonl shares
the bug. In production, `summary.txt` will never contain a per-agent row;
the integration test (`test_end_to_end.py:271-273`) only asserts
`summary.read_text().strip()` non-empty, so the regression is invisible.

**Action.** Fix `summary.py` to read `record.get("agent_name")` and switch
all `_invocation_pair` records in `test_summary.py` to `agent_name`. Add a
missing assertion to the e2e test: `"researcher" in summary` and
`"avg" in summary` so the contract is tested at the real boundary.

### T2. Tests assert the wrong arity for `responder_provider`

`responders/protocol.py:35` defines `ResponderProvider = Callable[[], Responder]`
(zero-arg). But `tests/agent_foundry/orchestration/test_run_context_hooks.py`
passes `responder_provider=lambda _id: lambda *a, **k: None` at lines
109, 139, 173, 212, 247, 288 — a one-arg lambda that does not match the
protocol. The tests pass because the FunctionAction-only plans never call
the provider. The contract is not exercised.

**Action.** Use `responder_provider=lambda: _StubResponder()` everywhere in
the hooks tests, or add a typed helper `static_provider(_StubResponder())`
already defined in `responders/protocol.py:38`.

### T3. Tests for code that has no production callers

The following test files exercise modules that no production code imports:

- `tests/agent_foundry/agents/test_agents_session.py` — covers
  `agents/session.py` (`SessionManager` / `SessionHandle`); no production
  importer outside its own test file.
- `tests/agent_foundry/agents/test_agents_recovery.py` — covers
  `agents/recovery.py` (`capture_workspace_state`, `WorkspaceSnapshot`); no
  production importer.
- `tests/agent_foundry/agents/test_agents_role_stack.py` — covers
  `agents/role_stack.py` (`RoleStack`); no production importer.
- `tests/agent_foundry/agents/test_agent_runner.py` — pins that
  `agents/agent_runner.py` re-exports `run_agent_in_container`; the module
  exists only to preserve the old import path.
- `tests/agent_foundry/agents/test_claude_code_events.py` — covers
  `parse_stream_event`; not on any production code path (see D2).

These tests give green CI but no production confidence; they raise the
maintenance bar with no upside.

**Action.** Either re-wire production code to use these modules (per D2 for
the events module; per a feature decision for session/recovery/role_stack)
or delete the modules and their tests. Half-on/half-off is the worst state.

### T4. Other test coverage gaps and weaknesses

- `_run_claude_turn` is tested only indirectly via the FakeRunTurn fakes;
  there is no unit test exercising the regex fallback path
  (`container_executor.py:173-185`) or the
  "no `StructuredOutput` captured" failure message.
- `_snapshot_container_artifacts` (`container_executor.py:208-262`) is
  invoked from a `finally:` block on every run. No test verifies that an
  exception in the snapshot does not mask the primary exception
  (`finally:` ordering bug surface).
- `ContainerManager.read_file_from_container` (`lifecycle.py:219-231`)
  catches every `Exception` and returns `None`. No test distinguishes
  "file genuinely missing" from "tarfile decoding raised because the
  container handed back garbage" — the host-side path verifier
  (`container_executor.py:265-280`) treats both as missing.
- `walk_file_path_fields` (`models/markers.py:69-106`) has a `visited` set
  guarding `$ref` cycles (line 82-84). No test exercises a self-referential
  schema. The branch is reachable in product schemas with recursive
  Pydantic models.
- `MAX_RESPONDER_ITERATIONS = 20` is tested for the simple "scripted past
  the cap" case (`test_container_executor.py:325-340`). No test verifies
  the cap interacts cleanly with cancellation between iterations.
- `JsonlLifecycleWriter` writes flushed-per-record and is thread-safe;
  no test exercises concurrent writes from multiple threads. Given that
  the orchestrator uses `asyncio.to_thread` for the per-turn shell out,
  this is a realistic scenario.
- `_compile_function_action` resolves run context via a `ContextVar` and
  emits FUNCTION_ACTION_*; the path where `current_run_context.get()` is
  None is exercised, but the path where the function raises *and* the
  ContextVar is None is not (the lifecycle emit branch is then skipped —
  which is correct, but the test gap means a future change can't trip a
  regression).
- `archetype/markdown/_projector.py:181-193` raises when an expected
  block is missing. No test covers the case where two consecutive AsTable
  fields share column names but different rows — the cursor-based search
  could grab the wrong table.
- The e2e integration test `test_end_to_end.py` is the only test that
  covers the full happy path with real Claude; there is no integration
  test for the file-path verification *failure* path against real Claude
  (only fakes), so a regression in the verifier's correction-prompt loop
  would not be caught at the integration tier.

### T5. `fakes.py` carries dead annotations

`tests/agent_foundry/orchestration/fakes.py:118-119, 128-129` re-declare
class-level annotations:
```python
read_file_script: dict[str, list[str | None]]
read_file_log: list[tuple[str, bool, int]]
copy_file_script: dict[str, str]
copy_file_log: list[tuple[str, str, bool]]
```
These shadow the same fields already initialized in `__init__`
(lines 67-69). The body methods (lines 134-141, 152-160) then do
"defensive lazy init" with `getattr(self, "copy_file_script", None)` —
also redundant, since `__init__` always sets them. Either the
annotations are dead or `__init__` is dead; both are present.

**Action.** Delete the loose class-level annotations and the lazy-init
blocks; rely on the `__init__` initializers.

---

## 3. Three most egregious technical debts

### TD1. `agent_runner.py` plus the four "agent module" files exist as docs only

`src/agent_foundry/agents/agent_runner.py` (9 LOC) is a re-export of
`run_agent_in_container` with the docstring "Legacy import path."
`agents/session.py` (130 LOC), `agents/recovery.py` (113 LOC),
`agents/role_stack.py` (30 LOC), and `agents/ansi.py` `strip_ansi` (15 LOC,
no callers in `src/`) all sit in the production package but no production
code imports them. Their only consumers are their own test files and
unreleased docs in `docs-staging/`.

That's roughly **300 LOC of dead source plus ~400 LOC of associated tests**
that grow CI time, expand the import-time module set, and, for any reader
new to the codebase, advertise functionality the platform does not actually
provide.

**Mitigation.**
- Decide which of the four modules belongs in the platform contract. The
  vision (`docs/agent-foundry-vision.md`) hints at recovery and role
  stacks as future capabilities; if so, document them and wire them in.
- Delete `agents/agent_runner.py` and its test file outright; the legacy
  import path serves no public guarantee and can be replaced by an explicit
  deprecation warning if any external consumer depends on it (the project
  predates `0.6.0`, internal-only).
- Move `ansi.py` into the place that actually formats stdin prompts (the
  `StdinResponder`) or delete it.

### TD2. `RunContext` smuggles untyped `Any` for two key collaborators

`src/agent_foundry/orchestration/run_context.py:83-84`:
```python
container_registry: Any
responder_provider: Any = None
```

The actual types are `AgentContainerRegistry` (in
`orchestration/registry.py`) and `ResponderProvider = Callable[[], Responder]`
(in `responders/protocol.py:35`). Neither carries any reason in the file's
docstrings to be `Any`; the only reason from the surrounding code
appears to be to defer a circular import.

Direct violation of the project's "Strict typing at all boundaries"
principle. Effects:
- Pyright cannot tell a caller of
  `run_ctx.container_registry.get_or_create(...)` whether the call is
  well-typed.
- Test fakes that should be cleanly substitutable have no static contract
  to honor; refactors like D1 (adding `exec_run` to `ContainerManagerBase`)
  cascade into runtime errors instead of compile-time errors.

**Mitigation.**
1. Use forward references (`if TYPE_CHECKING: from ... import
   AgentContainerRegistry`) and type the field as
   `AgentContainerRegistry`. Pydantic supports forward references and
   string annotations; with `arbitrary_types_allowed=True` already set,
   construction works.
2. Type `responder_provider` as `ResponderProvider | None`.
3. Same treatment to `lifecycle_writer: LifecycleWriter` (which is
   already correctly typed) — confirm none of the other product-extension
   fields drifted to `Any`.

### TD3. Hardcoded container paths and constants threaded through orchestration code

Multiple platform-shaped constants are inlined as module-level literals
or string literals at the call site:

- `src/agent_foundry/orchestration/registry.py:29` —
  `ROLE_INSTRUCTIONS_PATH = "/home/claude/role-instructions.md"`
- `src/agent_foundry/orchestration/container_executor.py:142` —
  `user="claude"` literal in `exec_run`
- `src/agent_foundry/orchestration/container_executor.py:251` —
  `"/home/claude/.claude/CLAUDE.md"` literal
- `src/agent_foundry/orchestration/registry.py:38-39` —
  `_DEFAULT_HEALTH_WAIT_TIMEOUT_SECONDS = 90.0`,
  `_HEALTH_POLL_INTERVAL_SECONDS = 0.25`
- `src/agent_foundry/orchestration/container_executor.py:71` —
  `MAX_RESPONDER_ITERATIONS = 20`

These describe the production container's filesystem layout. If a product
ships a base image that uses a different home path or a different agent
user (the foundational decision rule in `CLAUDE.md` says products should
be able to swap executors and base images), every literal here breaks.
The `AGENT_USER_UID = 1000` constant in `agents/__init__.py` is a precedent
for a typed surface — but the *paths* sit in three different files.

**Mitigation.**
1. Introduce `agents.image_layout: ImageLayout` (a frozen Pydantic model)
   with fields `home_dir`, `claude_md_path`, `role_instructions_path`,
   `agent_user_name`, `agent_user_uid`. Pin one default that matches the
   shipped base image and let products override.
2. Move `MAX_RESPONDER_ITERATIONS` to a `RunContext` field with a default,
   so tests can run with a tiny cap and products can run with a different
   value without monkeypatch.
3. Move `_DEFAULT_HEALTH_WAIT_TIMEOUT_SECONDS` onto the registry constructor
   public signature (already there for `health_wait_timeout_seconds` — but
   the default constant is private). Drop the leading underscore.

---

## 4. Other code-quality findings

### Q1. `mlflow.db` is checked into the repo root
A 663 KB SQLite file (`mlflow.db`) sits at the project root. It is not in
`.gitignore` (verified) and is showing up in `git status`. Move it under
`artifacts/` or `.tmp/` and add it to `.gitignore`; commit removal in a
separate change so any external collaborators rebase cleanly.

### Q2. Floating draft documents at the repo root
`URGENT-LSP-analysis.md`, `dockerfile-design-session-assessment.md`, and
multiple `docs-staging/...` drafts all sit alongside production docs. New
contributors (and the LSP-FIRST agent rule) end up reading these as if
they were authoritative. Move to `docs-staging/archive/` or delete after
extracting actionable items into `docs/`.

### Q3. Bare `except Exception:` blocks that silently swallow errors
- `src/agent_foundry/agents/lifecycle.py:230-231` —
  `read_file_from_container` returns `None` on *any* exception. The host-
  side path verifier interprets `None` as "file missing"; a transient
  docker error then maps to "AgentFilePath verification_failed", which
  feeds back into the agent as a correction prompt rather than a real
  diagnostic.
- `src/agent_foundry/agents/lifecycle.py:267-268` —
  `cleanup_all` swallows every exception with `pass`.
- `src/agent_foundry/orchestration/container_executor.py:438, 456, 467` —
  three separate `except Exception: logger.warning` for prompt/stream/envelope
  artifact persistence. Acceptable in a finally block, but the
  warning text repeats across every artifact; consider a single helper
  `try_write_artifact(turn_dir / name, …)`.

### Q4. Repeated dead imports inside hot loops
`src/agent_foundry/orchestration/container_executor.py:462, 544` —
`import json as _json` *inside* the per-turn loop, on the success path
each time. Move to module top.
Same pattern at `container_executor.py:229` (`from agent_foundry.orchestration.artifacts import agent_log_path` inside a function).

### Q5. Redundant tuple-membership check
`src/agent_foundry/agents/lifecycle.py:262` —
`if handle.status not in ("destroyed",)` — should be
`if handle.status != "destroyed"`.

### Q6. `ContainerManager.cleanup_all` and `validate_image` are dead in production
`src/agent_foundry/agents/lifecycle.py:184-201` (`validate_image`) and
`lifecycle.py:259-268` (`cleanup_all`) are never called by any production
code path; the registry uses `shutdown_all`. Tests cover them. Decide
whether they are public surface or remove them; if public, document them
on `ContainerManagerBase` so subclasses know the contract.

### Q7. `build_container_env(extra=...)` parameter is unused
`src/agent_foundry/orchestration/env.py:21` accepts `extra: dict[str, str] | None`.
The single caller (`registry.py:241-245`) never passes `extra=`. The dead
parameter masks itself as future-proofing and will rot. Remove until a
real caller appears.

### Q8. Schema-tools strip list is hard-coded
`src/agent_foundry/agents/schema_tools.py:48-64` strips three keys
(`discriminator`, `$defs`, `x-agent-file-path`) inside a single loop with
inline comments explaining why each is stripped. Each new orchestrator-
only metadata key that needs the same treatment will require editing this
function — exactly the "edit core to extend" anti-pattern the platform
principles forbid for primitives. Lift the list to a module-level
`STRIPPED_KEYS = frozenset({…})` and document it as a registration point
where products can add their own annotated metadata keys.

### Q9. `_invocation_count` is "private" but mutated externally
See D1; calling out separately because the `_count` naming convention is
itself a code-smell signaling that the design wants encapsulation but the
implementation doesn't deliver it.

### Q10. `tests/agent_foundry/orchestration/fakes.py` triple-defines fields
See T5 for the dead annotations and lazy-init duplication in
`FakeContainerManager`.

### Q11. `Annotated`-style `Any` typing on `LiveContainer.handle`/`manager`
`src/agent_foundry/orchestration/registry.py:50-52`:
```python
handle: ContainerHandleBase
manager: ContainerManagerBase
```
That part is good. But the fields the executor reaches through
(`live.handle._container.exec_run` etc.) drop back to `Any` because the
private attribute is `Any`-typed (see D1). `LiveContainer` is the one
abstraction that *should* have a fully typed surface — fix the surface
by lifting `exec_run`/`logs`/`reload` onto `ContainerManagerBase`.

### Q12. `runner.py:170-182` predicate-couples three independent decisions
```python
oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
registry = AgentContainerRegistry(
    …,
    oauth_token=oauth_token,
    inject_instructions=oauth_token is not None,
    wait_for_health=oauth_token is not None,
)
```
"Have an oauth token" is bound to "should inject instructions" and
"should wait for health". That coupling is a current implementation
detail (real container vs. fake), but the registry's API treats them as
independent flags. Either collapse to a single `_real_run: bool` flag or
drive the injection / health-wait decisions from a structural property
(e.g., the registry was constructed with `manager=` vs. with a docker
client factory).

### Q13. Project carries a `hide/` directory and `lab/` directory of unclear status
`hide/try-archetype.py`, `hide/itinerary-template.md`, `lab/...`. These
are not in `.gitignore` but appear to be experimental scratch space.
Either move them to `docs-staging/experiments/` or `.tmp/` (gitignored)
to keep the published source tree minimal.

### Q14. Inconsistent use of `Literal[Enum.VARIANT]` vs bare StrEnum on discriminator fields
`agent_turn_envelope.py:47, 51, 65, 72` and `responders/models.py:36, 45`
use `Literal[Enum.VARIANT] = Enum.VARIANT` per the project rule's
explicit fallback clause. The reasoning is documented in the file
docstrings, and that's good — but the rule is duplicated as inline
comments in two files. Lift the explanation into a single contributing
note (e.g., `docs/architecture/enum-discriminator-rule.md`) so future
discriminator additions don't have to re-derive the rule from the
inline comment.

---

## 5. Quick-win checklist (rough effort, biggest payoff first)

| # | Item | Effort | Impact |
|---|------|--------|--------|
| 1 | Fix `summary.py` + tests for `agent_name` field | XS | Restores observability on every run |
| 2 | Wire `parse_stream_event` into `_run_claude_turn` | S | Closes a typed-boundary leak; surfaces the `result.structured_output` path |
| 3 | Type `RunContext.container_registry` and `responder_provider` | S | Static type safety for the hottest API |
| 4 | Delete or wire in `agent_runner.py`, `session.py`, `recovery.py`, `role_stack.py`, `ansi.py` | S–M | Removes ~700 LOC of source+tests; reduces reader surprise |
| 5 | Lift `exec_run` / `logs` onto `ContainerManagerBase` | M | Closes the worst encapsulation hole; unblocks future executors |
| 6 | Move container-layout literals into a typed `ImageLayout` model | S | Removes hardcoded paths; prepares for non-default base images |
| 7 | Add `children()` registry; replace `PrimitivePlan._walk` `isinstance` chain | S | Restores extension parity with compiler/validator |
| 8 | `mlflow.db`, `URGENT-*.md`, `dockerfile-design-session-*.md` cleanup | XS | Repo hygiene |
