"""Inner-turn-loop tests for :func:`run_agent_in_container`.

Covers:

  * happy-path success envelopes
  * responder round-trip for ``ClarificationOutcome`` / ``PermissionOutcome``
  * reuse-policy dispatch (``REUSE_RESUME`` vs ``REUSE_NEW_SESSION``)
  * session-id recording on ``LiveContainer``
  * lifecycle event emission
  * file snapshotting on success
  * cancel_event check between turns
  * max 20 responder iterations per invocation
  * ``AgentFailedError`` paths (``FailureOutcome``, responder raises)

All tests inject a scripted ``FakeClaudeCodeDriver`` via the
``set_driver_factory`` module-level seam.
"""

from __future__ import annotations

import asyncio
import json as _json_test
from pathlib import Path
from typing import Annotated, Any

import pytest
from pydantic import BaseModel

from agent_foundry.agents.lifecycle import ExecResult as _ExecResult
from agent_foundry.models.markers import AgentFilePath
from agent_foundry.orchestration import container_executor
from agent_foundry.orchestration.artifacts import bootstrap_run_artifacts
from agent_foundry.orchestration.container_executor import (
    _run_claude_turn,
    _snapshot_container_artifacts,
    run_agent_in_container,
)
from agent_foundry.orchestration.errors import AgentFailedError
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.lifecycle_writer import LifecycleWriter
from agent_foundry.orchestration.registry import (
    AgentContainerRegistry,
)
from agent_foundry.orchestration.registry import (
    LiveContainer as _LiveContainer,
)
from agent_foundry.orchestration.run_context import RunContext
from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy
from agent_foundry.responders.protocol import static_provider

from .fakes import (
    FakeClaudeCodeDriver,
    FakeContainerManager,
    FakeResponder,
)

# --- Shared fixtures & helpers ----------------------------------------------


class CapturingLifecycleWriter(LifecycleWriter):
    """In-memory lifecycle writer capturing every ``append`` call."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def append(self, event_type: LifecycleEvent, **fields: Any) -> None:
        self.events.append({"type": event_type, **fields})

    def append_run_event(self, kind: str, **fields: Any) -> None:
        self.append(LifecycleEvent.DOMAIN, kind=kind, **fields)

    def close(self) -> None:
        return None

    def types(self) -> list[LifecycleEvent]:
        return [e["type"] for e in self.events]


class InputModel(BaseModel):
    task: str


class OutputModel(BaseModel):
    answer: str


class OutputWithFile(BaseModel):
    out_path: Annotated[str, AgentFilePath()]
    note: str


def _make_primitive(
    *,
    reuse_policy: ContainerReusePolicy = ContainerReusePolicy.REUSE_NEW_SESSION,
    output_type: type[BaseModel] = OutputModel,
    skip_permissions: bool = False,
    model: str = "claude-sonnet-4-6",
    effort: str | None = None,
) -> AgentAction:
    return AgentAction[InputModel, output_type](  # type: ignore[valid-type]
        name="test-agent",
        prompt_builder=lambda s: f"do: {s.task}",
        instructions_provider=lambda _s: "Be precise.",
        executor=run_agent_in_container,
        reuse_policy=reuse_policy,
        skip_permissions=skip_permissions,
        model=model,
        effort=effort,
    )


def _success_env(answer: str = "42") -> dict[str, Any]:
    return {"outcome": {"kind": "success", "payload": {"answer": answer}}}


def _clarification_env(question: str = "which branch?") -> dict[str, Any]:
    return {
        "outcome": {
            "kind": "clarification_needed",
            "question": question,
            "options": [],
            "blocking": True,
        }
    }


def _permission_env() -> dict[str, Any]:
    return {
        "outcome": {
            "kind": "permission_needed",
            "action": "delete /workspace/cache",
            "risk_level": "medium",
            "why_needed": "stale cache is blocking the build",
        }
    }


def _failure_env(reason: str = "cannot proceed") -> dict[str, Any]:
    return {"outcome": {"kind": "failed", "reason": reason, "attempted_approaches": []}}


def _make_ctx(
    *,
    tmp_path: Path,
    responder: Any | None = None,
    writer: Any | None = None,
    cancel_event: asyncio.Event | None = None,
    registry: AgentContainerRegistry | None = None,
    run_id: str = "run-f3",
) -> tuple[RunContext, AgentContainerRegistry, CapturingLifecycleWriter]:
    writer = writer or CapturingLifecycleWriter()
    fake_mgr = FakeContainerManager()
    if registry is None:
        registry = AgentContainerRegistry(
            manager=fake_mgr,
            base_image_tag="agent-foundry-base:test",
            workspace_volume="vol-f3",
        )
    # Bootstrap per-run artifacts dir so file-snapshotting tests work end-to-end.
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    run_dir = bootstrap_run_artifacts(
        artifacts_dir=artifacts_dir,
        run_id=run_id,
        workspace_volume="vol-f3",
        base_image_tag="agent-foundry-base:test",
    )
    ctx = RunContext(
        run_id=run_id,
        artifacts_dir=run_dir,
        container_registry=registry,
        responder_provider=(static_provider(responder) if responder is not None else None),
        lifecycle_writer=writer,
        cancel_event=cancel_event or asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    return ctx, registry, writer


def _install_driver(
    monkeypatch: pytest.MonkeyPatch,
    driver: FakeClaudeCodeDriver,
) -> None:
    """Replace the production ``_run_claude_turn`` helper with the scripted fake.

    ``FakeRunTurn`` / ``FakeClaudeCodeDriver`` is an awaitable callable
    matching the signature of :func:`container_executor._run_claude_turn`.
    Monkeypatching the module-level default at that symbol is equivalent
    to passing ``run_turn=<fake>`` to :func:`run_agent_in_container` and
    works for the indirect path via ``run_primitive_plan`` where the
    kwarg cannot be threaded through the compiler.
    """
    monkeypatch.setattr(container_executor, "_run_claude_turn", driver)


# --- Tests -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clarification_round_trip(monkeypatch, tmp_path) -> None:
    """ClarificationOutcome -> responder answer -> resumed success turn."""
    driver = FakeClaudeCodeDriver(
        turn_script=[_clarification_env("rebase or merge?"), _success_env("merged")],
        session_ids=["sess-fake-123", "sess-fake-123"],
    )
    _install_driver(monkeypatch, driver)
    responder = FakeResponder(answers=["rebase"])
    ctx, _, writer = _make_ctx(tmp_path=tmp_path, responder=responder)

    primitive = _make_primitive()
    result = await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)

    assert isinstance(result, OutputModel)
    assert result.answer == "merged"
    # Responder was called once.
    assert len(responder.calls) == 1
    # Second driver call's prompt is the responder's answer.
    assert len(driver.calls) == 2
    assert "rebase" in driver.calls[1]["prompt"]
    assert driver.calls[1]["resume"] == "sess-fake-123"
    # Lifecycle saw responder_requested + responder_answered.
    assert LifecycleEvent.RESPONDER_REQUESTED in writer.types()
    assert LifecycleEvent.RESPONDER_ANSWERED in writer.types()


@pytest.mark.asyncio
async def test_permission_round_trip(monkeypatch, tmp_path) -> None:
    """PermissionOutcome -> responder 'allow' -> resumed success turn."""
    driver = FakeClaudeCodeDriver(
        turn_script=[_permission_env(), _success_env("done")],
        session_ids=["sess-perm", "sess-perm"],
    )
    _install_driver(monkeypatch, driver)
    responder = FakeResponder(answers=["allow"])
    ctx, _, writer = _make_ctx(tmp_path=tmp_path, responder=responder)

    primitive = _make_primitive()
    result = await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)

    assert isinstance(result, OutputModel)
    assert result.answer == "done"
    assert len(responder.calls) == 1
    assert "allow" in driver.calls[1]["prompt"]
    assert driver.calls[1]["resume"] == "sess-perm"
    assert LifecycleEvent.RESPONDER_REQUESTED in writer.types()
    assert LifecycleEvent.RESPONDER_ANSWERED in writer.types()


@pytest.mark.asyncio
async def test_failure_outcome_raises_agent_failed(monkeypatch, tmp_path) -> None:
    driver = FakeClaudeCodeDriver(turn_script=[_failure_env("cannot proceed")])
    _install_driver(monkeypatch, driver)
    ctx, _, writer = _make_ctx(tmp_path=tmp_path)

    primitive = _make_primitive()
    with pytest.raises(AgentFailedError) as excinfo:
        await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)
    assert "cannot proceed" in excinfo.value.reason
    assert LifecycleEvent.AGENT_INVOCATION_FAILED in writer.types()


@pytest.mark.asyncio
async def test_responder_exception_wrapped_as_agent_failed(monkeypatch, tmp_path) -> None:
    driver = FakeClaudeCodeDriver(turn_script=[_clarification_env()])
    _install_driver(monkeypatch, driver)
    responder = FakeResponder(raise_on_call=TimeoutError("responder timed out"))
    ctx, _, writer = _make_ctx(tmp_path=tmp_path, responder=responder)

    primitive = _make_primitive()
    with pytest.raises(AgentFailedError) as excinfo:
        await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)
    assert "responder failed" in excinfo.value.reason
    assert LifecycleEvent.AGENT_INVOCATION_FAILED in writer.types()


@pytest.mark.asyncio
async def test_cancel_event_between_turns(monkeypatch, tmp_path) -> None:
    """cancel_event.set() between turns -> AgentFailedError('cancelled')."""
    cancel = asyncio.Event()
    responder = FakeResponder(answers=["whatever"])

    # First turn returns clarification; responder side-effects by setting
    # the cancel event so the loop bails before driver.run_turn #2.
    async def _set_and_answer(request: Any, context: Any) -> Any:
        cancel.set()
        from agent_foundry.responders.models import ResponderResponse

        return ResponderResponse(answer="whatever")

    responder.respond = _set_and_answer  # type: ignore[method-assign]

    driver = FakeClaudeCodeDriver(turn_script=[_clarification_env(), _success_env()])
    _install_driver(monkeypatch, driver)
    ctx, _, _ = _make_ctx(tmp_path=tmp_path, responder=responder, cancel_event=cancel)

    primitive = _make_primitive()
    with pytest.raises(AgentFailedError) as excinfo:
        await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)
    assert "cancel" in excinfo.value.reason.lower()


@pytest.mark.asyncio
async def test_reuse_resume_passes_session_id_on_second_call(monkeypatch, tmp_path) -> None:
    """REUSE_RESUME: second invocation gets the first call's captured session id."""
    driver = FakeClaudeCodeDriver(
        turn_script=[_success_env("first"), _success_env("second")],
        session_ids=["sess-carry-1", "sess-carry-2"],
    )
    _install_driver(monkeypatch, driver)
    ctx, _registry, _ = _make_ctx(tmp_path=tmp_path)

    primitive = _make_primitive(reuse_policy=ContainerReusePolicy.REUSE_RESUME)
    r1 = await run_agent_in_container(primitive=primitive, prompt="go 1", run_ctx=ctx)
    r2 = await run_agent_in_container(primitive=primitive, prompt="go 2", run_ctx=ctx)

    assert r1.answer == "first"  # type: ignore[attr-defined]
    assert r2.answer == "second"  # type: ignore[attr-defined]
    # First invocation passed resume=None; second passed the captured sid.
    assert driver.calls[0]["resume"] is None
    assert driver.calls[1]["resume"] == "sess-carry-1"


@pytest.mark.asyncio
async def test_reuse_new_session_never_resumes(monkeypatch, tmp_path) -> None:
    """REUSE_NEW_SESSION: second invocation passes resume=None regardless."""
    driver = FakeClaudeCodeDriver(
        turn_script=[_success_env("a"), _success_env("b")],
        session_ids=["sess-1", "sess-2"],
    )
    _install_driver(monkeypatch, driver)
    ctx, _, _ = _make_ctx(tmp_path=tmp_path)

    primitive = _make_primitive(reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION)
    await run_agent_in_container(primitive=primitive, prompt="go 1", run_ctx=ctx)
    await run_agent_in_container(primitive=primitive, prompt="go 2", run_ctx=ctx)

    assert driver.calls[0]["resume"] is None
    assert driver.calls[1]["resume"] is None


@pytest.mark.asyncio
async def test_max_responder_loops_exceeded(monkeypatch, tmp_path) -> None:
    """25 consecutive clarifications -> AgentFailedError on iteration 21."""
    driver = FakeClaudeCodeDriver(
        turn_script=[_clarification_env() for _ in range(25)],
        session_ids=["sess-loop"],
    )
    _install_driver(monkeypatch, driver)
    responder = FakeResponder(answers=["answer"] * 25)
    ctx, _, _ = _make_ctx(tmp_path=tmp_path, responder=responder)

    primitive = _make_primitive()
    with pytest.raises(AgentFailedError) as excinfo:
        await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)
    assert "responder loop exceeded max iterations" in excinfo.value.reason
    # Bound is 20 — should have invoked the driver no more than 21 times.
    assert len(driver.calls) <= 21


@pytest.mark.asyncio
async def test_file_snapshotting_on_success(monkeypatch, tmp_path) -> None:
    """SuccessOutcome with AgentFilePath field -> file copied into turn dir."""
    env_payload = {
        "outcome": {
            "kind": "success",
            "payload": {"out_path": "/workspace/out.txt", "note": "ok"},
        }
    }
    driver = FakeClaudeCodeDriver(
        turn_script=[env_payload],
        session_ids=["sess-snap"],
    )
    _install_driver(monkeypatch, driver)
    ctx, registry, _ = _make_ctx(tmp_path=tmp_path)
    # Seed the fake manager's copy_from_container script.
    fake_mgr: FakeContainerManager = registry._manager_override  # type: ignore[assignment]
    fake_mgr.copy_file_script = {"/workspace/out.txt": "hello"}
    # Also seed read_file_from_container so host-side file-path verification passes.
    fake_mgr.read_file_script = {"/workspace/out.txt": ["hello"]}

    primitive = _make_primitive(output_type=OutputWithFile)
    result = await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)
    assert isinstance(result, OutputWithFile)

    agent_name = primitive.name
    snapshot = ctx.artifacts_dir / agent_name / "turns" / "1" / "collected_files" / "out.txt"
    assert snapshot.exists(), f"expected snapshot at {snapshot}"
    assert snapshot.read_text() == "hello"


@pytest.mark.asyncio
async def test_session_id_recorded_on_live_container(monkeypatch, tmp_path) -> None:
    """After the first successful turn, LiveContainer.session_id == captured sid."""
    driver = FakeClaudeCodeDriver(
        turn_script=[_success_env()],
        session_ids=["sess-fake-123"],
    )
    _install_driver(monkeypatch, driver)
    ctx, registry, _ = _make_ctx(tmp_path=tmp_path)

    primitive = _make_primitive(reuse_policy=ContainerReusePolicy.REUSE_RESUME)
    await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)

    live = registry._containers.get(id(primitive))
    assert live is not None, "primitive should have been registered"
    assert live.session_id == "sess-fake-123"


@pytest.mark.asyncio
async def test_lifecycle_event_sequence_on_success(monkeypatch, tmp_path) -> None:
    """Full success run emits the expected lifecycle event sequence in order."""
    driver = FakeClaudeCodeDriver(
        turn_script=[_success_env()],
        session_ids=["sess-evt"],
    )
    _install_driver(monkeypatch, driver)
    ctx, _, writer = _make_ctx(tmp_path=tmp_path)

    primitive = _make_primitive()
    await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)

    types = writer.types()
    expected = [
        LifecycleEvent.AGENT_INVOCATION_STARTED,
        LifecycleEvent.TURN_STARTED,
        LifecycleEvent.TURN_COMPLETED,
        LifecycleEvent.AGENT_INVOCATION_COMPLETED,
    ]
    # Verify each expected event appears and their relative order holds.
    idx = -1
    for event in expected:
        assert event in types, f"missing lifecycle event: {event} (got {types})"
        new_idx = types.index(event, idx + 1)
        assert new_idx > idx, f"event {event} out of order in {types}"
        idx = new_idx


# --- Happy-path smoke tests --------------------------------------------------
#
# These use the minimal ``NoOpLifecycleWriter`` + no artifacts directory and
# the simpler ``OutputModel`` (no file-path fields). They predate the full
# inner-loop suite above and cover the two smallest driver contracts:
# a single-turn success and a single-turn failure.


def _make_smoke_primitive() -> AgentAction[InputModel, OutputModel]:
    return AgentAction[InputModel, OutputModel](
        name="test-agent",
        model="claude-sonnet-4-6",
        prompt_builder=lambda s: f"do: {s.task}",
        instructions_provider=lambda _s: "Be precise.",
        executor=run_agent_in_container,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    )


@pytest.mark.asyncio
async def test_run_agent_in_container_happy_path(monkeypatch) -> None:
    from agent_foundry.orchestration.run_context import NoOpLifecycleWriter

    driver = FakeClaudeCodeDriver(
        turn_script=[
            {"outcome": {"kind": "success", "payload": {"answer": "42"}}},
        ],
        session_ids=["sess-smoke"],
    )
    _install_driver(monkeypatch, driver)

    fake_mgr = FakeContainerManager()
    registry = AgentContainerRegistry(
        manager=fake_mgr,
        base_image_tag="agent-foundry-base:test",
        workspace_volume="vol-smoke",
    )
    ctx = RunContext(
        run_id="run-smoke",
        container_registry=registry,
        lifecycle_writer=NoOpLifecycleWriter(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    primitive = _make_smoke_primitive()
    result = await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)
    assert isinstance(result, OutputModel)
    assert result.answer == "42"
    # Container was created and is running; the lifecycle keeps the
    # container alive for subsequent invocations (destroyed by
    # registry.shutdown_all at end of run).
    assert fake_mgr.handles[0].status == "running"
    # Driver contract: records per-call args.
    assert len(driver.calls) == 1
    assert driver.calls[0]["resume"] is None


@pytest.mark.asyncio
async def test_run_agent_in_container_failure_outcome_raises(monkeypatch) -> None:
    """FailureOutcome surfaces as AgentFailedError."""
    from agent_foundry.orchestration.run_context import NoOpLifecycleWriter

    driver = FakeClaudeCodeDriver(
        turn_script=[
            {
                "outcome": {
                    "kind": "failed",
                    "reason": "cannot proceed",
                    "attempted_approaches": [],
                }
            }
        ],
        session_ids=["sess-smoke-fail"],
    )
    _install_driver(monkeypatch, driver)

    fake_mgr = FakeContainerManager()
    registry = AgentContainerRegistry(
        manager=fake_mgr,
        base_image_tag="x",
        workspace_volume="v",
    )
    ctx = RunContext(
        run_id="r",
        container_registry=registry,
        lifecycle_writer=NoOpLifecycleWriter(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "t"},
    )
    primitive = _make_smoke_primitive()
    with pytest.raises(AgentFailedError) as excinfo:
        await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx)
    assert "cannot proceed" in excinfo.value.reason


# --- _run_claude_turn against a FakeContainerManager ------------------------
#
# Until step 5 of the D1 refactor, _run_claude_turn reached past
# manager via live.handle._container.exec_run — making it impossible to
# fake the per-turn shell-out via the typed surface. These tests
# exercise the real production helper against FakeContainerManager
# (which now implements ContainerManagerBase.exec_run / read_logs)
# and act as a permanent guard against the executor reintroducing the
# leak. They cover: success path; non-zero exit → RuntimeError with
# logs; missing envelope → RuntimeError; ` ```json ` text-block
# fallback path.


def _stream_lines(*events: dict[str, Any]) -> bytes:
    return ("\n".join(_json_test.dumps(e) for e in events) + "\n").encode()


def _make_live_with_fake_mgr(
    fake_mgr: FakeContainerManager,
) -> tuple[_LiveContainer, FakeContainerManager]:
    handle = fake_mgr.create_container()
    fake_mgr.start(handle)
    live = _LiveContainer(handle=handle, manager=fake_mgr)
    return live, fake_mgr


@pytest.mark.asyncio
async def test_run_claude_turn_uses_manager_exec_run_for_success() -> None:
    fake_mgr = FakeContainerManager()
    live, _ = _make_live_with_fake_mgr(fake_mgr)
    payload = {"outcome": {"kind": "success", "payload": {"answer": "42"}}}
    init_evt = {"type": "system", "subtype": "init", "session_id": "sess-z"}
    asst_evt = {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "StructuredOutput", "input": payload}]
        },
    }
    # Script the upcoming exec call. _run_claude_turn assembles the cmd
    # internally; we script by tuple of args.
    cmd = (
        "gosu",
        "claude",
        "/home/claude/.local/bin/claude",
        "-p",
        "go",
        "--output-format",
        "stream-json",
        "--verbose",
        "--json-schema",
        "{}",
        "--model",
        "claude-sonnet-4-6",
    )
    fake_mgr.exec_script[cmd] = _ExecResult(exit_code=0, output=_stream_lines(init_evt, asst_evt))

    result = await _run_claude_turn(
        live, prompt="go", resume_session_id=None, schema={}, model="claude-sonnet-4-6"
    )
    assert result.envelope == payload
    assert result.session_id == "sess-z"


@pytest.mark.asyncio
async def test_run_claude_turn_raises_on_nonzero_exit_with_log_tail() -> None:
    fake_mgr = FakeContainerManager()
    live, _ = _make_live_with_fake_mgr(fake_mgr)
    cmd = (
        "gosu",
        "claude",
        "/home/claude/.local/bin/claude",
        "-p",
        "go",
        "--output-format",
        "stream-json",
        "--verbose",
        "--json-schema",
        "{}",
        "--model",
        "claude-sonnet-4-6",
    )
    fake_mgr.exec_script[cmd] = _ExecResult(exit_code=2, output=b"boom-stderr")
    fake_mgr.logs_script[live.handle.container_id] = b"recent log line\n"

    with pytest.raises(RuntimeError, match="claude exec failed"):
        await _run_claude_turn(
            live, prompt="go", resume_session_id=None, schema={}, model="claude-sonnet-4-6"
        )
    # The diagnostic must have gone through manager.read_logs (not the
    # docker-SDK escape hatch).
    assert any(
        cid == live.handle.container_id and entry["tail"] == 80 for cid, entry in fake_mgr.logs_log
    )


@pytest.mark.asyncio
async def test_run_claude_turn_raises_when_no_envelope_extractable() -> None:
    fake_mgr = FakeContainerManager()
    live, _ = _make_live_with_fake_mgr(fake_mgr)
    cmd = (
        "gosu",
        "claude",
        "/home/claude/.local/bin/claude",
        "-p",
        "go",
        "--output-format",
        "stream-json",
        "--verbose",
        "--json-schema",
        "{}",
        "--model",
        "claude-sonnet-4-6",
    )
    # No assistant tool_use, no fallback text: just init.
    init_evt = {"type": "system", "subtype": "init", "session_id": "sess-x"}
    fake_mgr.exec_script[cmd] = _ExecResult(exit_code=0, output=_stream_lines(init_evt))

    with pytest.raises(RuntimeError, match="no StructuredOutput"):
        await _run_claude_turn(
            live, prompt="go", resume_session_id=None, schema={}, model="claude-sonnet-4-6"
        )


@pytest.mark.asyncio
async def test_run_claude_turn_falls_back_to_json_text_block() -> None:
    """Claude sometimes emits the envelope as a ```json …``` text block
    rather than a StructuredOutput tool_use, despite --json-schema."""
    fake_mgr = FakeContainerManager()
    live, _ = _make_live_with_fake_mgr(fake_mgr)
    cmd = (
        "gosu",
        "claude",
        "/home/claude/.local/bin/claude",
        "-p",
        "go",
        "--output-format",
        "stream-json",
        "--verbose",
        "--json-schema",
        "{}",
        "--model",
        "claude-sonnet-4-6",
    )
    init_evt = {"type": "system", "subtype": "init", "session_id": "sess-fb"}
    text = '```json\n{"outcome": {"kind": "success", "payload": {"answer": "fb"}}}\n```'
    asst_evt = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }
    fake_mgr.exec_script[cmd] = _ExecResult(exit_code=0, output=_stream_lines(init_evt, asst_evt))

    result = await _run_claude_turn(
        live, prompt="go", resume_session_id=None, schema={}, model="claude-sonnet-4-6"
    )
    assert result.envelope["outcome"]["kind"] == "success"
    assert result.envelope["outcome"]["payload"]["answer"] == "fb"


# --- skip_permissions → --dangerously-skip-permissions ----------------------


class TestRunClaudeTurnSkipPermissions:
    """_run_claude_turn adds --dangerously-skip-permissions iff skip_permissions=True."""

    @pytest.mark.asyncio
    async def test_given_skip_permissions_false_then_dangerous_flag_absent(self) -> None:
        fake_mgr = FakeContainerManager()
        live, _ = _make_live_with_fake_mgr(fake_mgr)

        with pytest.raises(RuntimeError):
            await _run_claude_turn(
                live,
                prompt="go",
                resume_session_id=None,
                schema={},
                skip_permissions=False,
                model="claude-sonnet-4-6",
            )

        cmd = fake_mgr.exec_calls[0]["cmd"]
        assert "--dangerously-skip-permissions" not in cmd

    @pytest.mark.asyncio
    async def test_given_skip_permissions_true_then_dangerous_flag_present(self) -> None:
        fake_mgr = FakeContainerManager()
        live, _ = _make_live_with_fake_mgr(fake_mgr)

        with pytest.raises(RuntimeError):
            await _run_claude_turn(
                live,
                prompt="go",
                resume_session_id=None,
                schema={},
                skip_permissions=True,
                model="claude-sonnet-4-6",
            )

        cmd = fake_mgr.exec_calls[0]["cmd"]
        assert "--dangerously-skip-permissions" in cmd


class TestRunAgentInContainerSkipPermissionsThreading:
    """run_agent_in_container threads primitive.skip_permissions to run_turn."""

    @pytest.mark.asyncio
    async def test_given_primitive_skip_true_then_run_turn_receives_true(self, tmp_path) -> None:
        driver = FakeClaudeCodeDriver(turn_script=[_success_env()])
        ctx, _, _ = _make_ctx(tmp_path=tmp_path)
        primitive = _make_primitive(skip_permissions=True)

        await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx, run_turn=driver)

        assert driver.calls[0]["skip_permissions"] is True

    @pytest.mark.asyncio
    async def test_given_primitive_skip_false_then_run_turn_receives_false(self, tmp_path) -> None:
        driver = FakeClaudeCodeDriver(turn_script=[_success_env()])
        ctx, _, _ = _make_ctx(tmp_path=tmp_path)
        primitive = _make_primitive(skip_permissions=False)

        await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx, run_turn=driver)

        assert driver.calls[0]["skip_permissions"] is False


# --- model → --model -------------------------------------------------------


class TestRunClaudeTurnModel:
    """_run_claude_turn passes --model <value> to the claude CLI."""

    @pytest.mark.asyncio
    async def test_given_model_then_flag_present_in_cmd(self) -> None:
        fake_mgr = FakeContainerManager()
        live, _ = _make_live_with_fake_mgr(fake_mgr)

        with pytest.raises(RuntimeError):
            await _run_claude_turn(
                live, prompt="go", resume_session_id=None, schema={}, model="claude-sonnet-4-6"
            )

        cmd = fake_mgr.exec_calls[0]["cmd"]
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_given_different_model_then_value_forwarded(self) -> None:
        fake_mgr = FakeContainerManager()
        live, _ = _make_live_with_fake_mgr(fake_mgr)

        with pytest.raises(RuntimeError):
            await _run_claude_turn(
                live, prompt="go", resume_session_id=None, schema={}, model="claude-opus-4-7"
            )

        cmd = fake_mgr.exec_calls[0]["cmd"]
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "claude-opus-4-7"


class TestRunAgentInContainerModelThreading:
    """run_agent_in_container threads primitive.model to run_turn."""

    @pytest.mark.asyncio
    async def test_given_primitive_model_then_run_turn_receives_it(self, tmp_path) -> None:
        driver = FakeClaudeCodeDriver(turn_script=[_success_env()])
        ctx, _, _ = _make_ctx(tmp_path=tmp_path)
        primitive = _make_primitive(model="claude-opus-4-7")

        await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx, run_turn=driver)

        assert driver.calls[0]["model"] == "claude-opus-4-7"


# --- effort → --effort -------------------------------------------------------


class TestRunClaudeTurnEffort:
    """_run_claude_turn passes --effort <value> only when effort is set."""

    @pytest.mark.asyncio
    async def test_given_effort_then_flag_present_in_cmd(self) -> None:
        fake_mgr = FakeContainerManager()
        live, _ = _make_live_with_fake_mgr(fake_mgr)

        with pytest.raises(RuntimeError):
            await _run_claude_turn(
                live,
                prompt="go",
                resume_session_id=None,
                schema={},
                model="claude-sonnet-4-6",
                effort="high",
            )

        cmd = fake_mgr.exec_calls[0]["cmd"]
        assert "--effort" in cmd
        idx = cmd.index("--effort")
        assert cmd[idx + 1] == "high"

    @pytest.mark.asyncio
    async def test_given_effort_none_then_flag_absent_from_cmd(self) -> None:
        fake_mgr = FakeContainerManager()
        live, _ = _make_live_with_fake_mgr(fake_mgr)

        with pytest.raises(RuntimeError):
            await _run_claude_turn(
                live,
                prompt="go",
                resume_session_id=None,
                schema={},
                model="claude-sonnet-4-6",
                effort=None,
            )

        cmd = fake_mgr.exec_calls[0]["cmd"]
        assert "--effort" not in cmd

    @pytest.mark.asyncio
    async def test_given_different_effort_value_then_value_forwarded(self) -> None:
        fake_mgr = FakeContainerManager()
        live, _ = _make_live_with_fake_mgr(fake_mgr)

        with pytest.raises(RuntimeError):
            await _run_claude_turn(
                live,
                prompt="go",
                resume_session_id=None,
                schema={},
                model="claude-sonnet-4-6",
                effort="max",
            )

        cmd = fake_mgr.exec_calls[0]["cmd"]
        idx = cmd.index("--effort")
        assert cmd[idx + 1] == "max"


class TestRunAgentInContainerEffortThreading:
    """run_agent_in_container threads primitive.effort to run_turn."""

    @pytest.mark.asyncio
    async def test_given_primitive_effort_then_run_turn_receives_it(self, tmp_path) -> None:
        driver = FakeClaudeCodeDriver(turn_script=[_success_env()])
        ctx, _, _ = _make_ctx(tmp_path=tmp_path)
        primitive = _make_primitive(effort="high")

        await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx, run_turn=driver)

        assert driver.calls[0]["effort"] == "high"

    @pytest.mark.asyncio
    async def test_given_no_effort_declared_then_run_turn_receives_none(self, tmp_path) -> None:
        driver = FakeClaudeCodeDriver(turn_script=[_success_env()])
        ctx, _, _ = _make_ctx(tmp_path=tmp_path)
        primitive = _make_primitive()  # effort not declared → defaults to None

        await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx, run_turn=driver)

        assert driver.calls[0]["effort"] is None


# --- Postmortem snapshot tests ----------------------------------------------
#
# Tests for ``_snapshot_container_artifacts`` directly. The function runs
# in the ``finally`` of every ``run_agent_in_container`` invocation and is
# the only on-disk record once the container is destroyed.


class TestSnapshotContainerArtifacts:
    """Postmortem snapshot of container state for offline forensics.

    Always writes ``container.log`` and ``CLAUDE.md``; with step 2 of the
    container-failure-postmortem design, also writes ``docker-inspect.json``
    and ``cgroup-memory.txt``. Each write is best-effort (a failure in one
    must not prevent the others).
    """

    def _make_live(self, fake_mgr: FakeContainerManager) -> _LiveContainer:
        handle = fake_mgr.create_container()
        return _LiveContainer(
            handle=handle,
            manager=fake_mgr,
            agent_name="test-agent",
        )

    def test_writes_docker_inspect_json(self, tmp_path: Path) -> None:
        fake_mgr = FakeContainerManager()
        live = self._make_live(fake_mgr)
        fake_mgr.inspect_script = {
            live.handle.container_id: {
                "State": {"ExitCode": 137, "OOMKilled": True, "Status": "exited"},
                "Id": "abc",
            }
        }

        _snapshot_container_artifacts(live, tmp_path, "test-agent")

        inspect_path = tmp_path / "test-agent" / "docker-inspect.json"
        assert inspect_path.exists(), f"expected inspect snapshot at {inspect_path}"
        data = _json_test.loads(inspect_path.read_text())
        assert data["State"]["ExitCode"] == 137
        assert data["State"]["OOMKilled"] is True

    def test_writes_cgroup_memory_txt(self, tmp_path: Path) -> None:
        fake_mgr = FakeContainerManager()
        live = self._make_live(fake_mgr)
        # Cgroup reads now go through exec_run + cat (sysfs pseudo-files
        # do not tar-archive). Script exec_run accordingly.
        fake_mgr.exec_script = {
            ("cat", "/sys/fs/cgroup/memory.events"): _ExecResult(
                exit_code=0,
                output=b"low 0\nhigh 0\nmax 1167\noom 0\noom_kill 0\noom_group_kill 0\n",
            ),
            ("cat", "/sys/fs/cgroup/memory.peak"): _ExecResult(exit_code=0, output=b"3221225472\n"),
            ("cat", "/sys/fs/cgroup/memory.current"): _ExecResult(exit_code=0, output=b"9981952\n"),
            ("cat", "/sys/fs/cgroup/memory.max"): _ExecResult(exit_code=0, output=b"3221225472\n"),
        }

        _snapshot_container_artifacts(live, tmp_path, "test-agent")

        cgroup_path = tmp_path / "test-agent" / "cgroup-memory.txt"
        assert cgroup_path.exists(), f"expected cgroup snapshot at {cgroup_path}"
        content = cgroup_path.read_text()
        # Each scripted file appears, with its path as a header so a reader
        # can disambiguate.
        for header in (
            "/sys/fs/cgroup/memory.events",
            "/sys/fs/cgroup/memory.peak",
            "/sys/fs/cgroup/memory.current",
            "/sys/fs/cgroup/memory.max",
        ):
            assert header in content, f"missing section header {header} in {content!r}"
        assert "oom_kill" in content
        assert "3221225472" in content

    def test_cgroup_missing_files_handled_gracefully(self, tmp_path: Path) -> None:
        # On a host without cgroup v2 (or in test environments without
        # scripted exec_run output), the reads come back empty. The
        # snapshot must still write the file with a diagnostic line per
        # missing entry rather than crash.
        fake_mgr = FakeContainerManager()
        live = self._make_live(fake_mgr)
        # No exec_script entries — fake's exec_run returns (0, b"") by
        # default, which _read_cgroup_text treats as unavailable.

        _snapshot_container_artifacts(live, tmp_path, "test-agent")

        cgroup_path = tmp_path / "test-agent" / "cgroup-memory.txt"
        assert cgroup_path.exists()
        content = cgroup_path.read_text()
        # All four expected paths still appear as section headers, marked
        # missing rather than absent.
        assert content.count("(unavailable)") == 4


# --- Failed-turn raw-output persistence -------------------------------------
#
# When a run_turn implementation raises ClaudeExecFailedError (the typed
# exception _do_exec emits on exit_code != 0 or no-envelope-captured),
# the executor must persist the raw output to turns/<N>/stream.jsonl
# before the exception propagates. Today the raw output is mashed into
# the agent_invocation_failed event's reason field (215 KB blob) — this
# step makes it a first-class on-disk artifact.


class TestFailedTurnStreamJsonl:
    @pytest.mark.asyncio
    async def test_failed_turn_persists_stream_jsonl(self, tmp_path: Path) -> None:
        from agent_foundry.orchestration.container_executor import (
            ClaudeExecFailedError,
        )

        raw = b'{"type":"system","subtype":"init","session_id":"s1"}\n'

        async def failing_turn(*args: Any, **kwargs: Any) -> Any:
            raise ClaudeExecFailedError(
                "claude exec failed (exit=137)",
                exit_code=137,
                output=raw,
                container_logs="",
            )

        ctx, _, _ = _make_ctx(tmp_path=tmp_path)
        primitive = _make_primitive()

        with pytest.raises(AgentFailedError):
            await run_agent_in_container(
                primitive=primitive,
                prompt="go",
                run_ctx=ctx,
                run_turn=failing_turn,
            )

        stream_path = ctx.artifacts_dir / "test-agent" / "turns" / "1" / "stream.jsonl"
        assert stream_path.exists(), f"expected failed-turn stream.jsonl at {stream_path}"
        assert stream_path.read_bytes() == raw

    @pytest.mark.asyncio
    async def test_failed_turn_persists_even_when_output_is_large(self, tmp_path: Path) -> None:
        # Capped at 100 MiB per the design doc. An output larger than
        # the cap should be truncated, not dropped, with a marker that
        # it was truncated.
        from agent_foundry.orchestration.container_executor import (
            ClaudeExecFailedError,
        )

        # 110 MiB of "x" — well over the 100 MiB cap.
        raw = b"x" * (110 * 1024 * 1024)

        async def failing_turn(*args: Any, **kwargs: Any) -> Any:
            raise ClaudeExecFailedError(
                "claude exec failed (exit=1)",
                exit_code=1,
                output=raw,
                container_logs="",
            )

        ctx, _, _ = _make_ctx(tmp_path=tmp_path)
        primitive = _make_primitive()

        with pytest.raises(AgentFailedError):
            await run_agent_in_container(
                primitive=primitive,
                prompt="go",
                run_ctx=ctx,
                run_turn=failing_turn,
            )

        stream_path = ctx.artifacts_dir / "test-agent" / "turns" / "1" / "stream.jsonl"
        assert stream_path.exists()
        # File is written but capped at the 100 MiB limit.
        size = stream_path.stat().st_size
        assert size <= 100 * 1024 * 1024 + 1024, (
            f"expected stream.jsonl <= 100 MiB (with small marker slack), got {size}"
        )
        # Truncation marker present in the file.
        tail = stream_path.read_bytes()[-200:]
        assert b"truncated" in tail.lower()


# --- Enriched agent_invocation_failed event ---------------------------------
#
# On unexpected container/exec failures, the AGENT_INVOCATION_FAILED
# lifecycle event payload now carries structured forensic fields
# (exit_code, oom_killed, memory_peak_bytes) alongside the existing
# `reason` string. Common dispatch becomes a one-line check instead
# of parsing the 215 KB reason blob.


class TestAgentInvocationFailedEventEnrichment:
    @pytest.mark.asyncio
    async def test_event_includes_oom_killed_exit_code_memory_peak(self, tmp_path: Path) -> None:
        from agent_foundry.orchestration.container_executor import (
            ClaudeExecFailedError,
        )

        async def failing_turn(*args: Any, **kwargs: Any) -> Any:
            raise ClaudeExecFailedError(
                "claude exec failed (exit=137)",
                exit_code=137,
                output=b"",
                container_logs="",
            )

        ctx, registry, writer = _make_ctx(tmp_path=tmp_path)
        # Pre-script the manager so the forensic capture finds usable data.
        fake_mgr: FakeContainerManager = registry._manager_override  # type: ignore[assignment]
        # inspect returns OOMKilled=True; container_id is assigned when the
        # registry calls create_container, so script the *path-agnostic*
        # default — see fake's inspect_script behavior — by populating
        # it with the actual id once the container is created. The test
        # here uses a special pre-script approach via create_container.

        # Pre-create the container by registering primitive — done inside
        # run_agent_in_container, after our setup runs. To set the inspect
        # script for the right container_id, hook create_container.
        orig_create = fake_mgr.create_container

        def _create_and_script(*a: Any, **kw: Any) -> Any:
            h = orig_create(*a, **kw)
            fake_mgr.inspect_script[h.container_id] = {
                "State": {"ExitCode": 137, "OOMKilled": True, "Status": "exited"}
            }
            return h

        fake_mgr.inspect_script = {}
        fake_mgr.create_container = _create_and_script  # type: ignore[method-assign]
        # memory.peak now sourced via exec_run + cat.
        fake_mgr.exec_script = {
            ("cat", "/sys/fs/cgroup/memory.peak"): _ExecResult(exit_code=0, output=b"3221229568\n"),
        }

        primitive = _make_primitive()

        with pytest.raises(AgentFailedError):
            await run_agent_in_container(
                primitive=primitive,
                prompt="go",
                run_ctx=ctx,
                run_turn=failing_turn,
            )

        failed_events = [
            e for e in writer.events if e["type"] is LifecycleEvent.AGENT_INVOCATION_FAILED
        ]
        assert len(failed_events) == 1, f"expected exactly one failure event, got {writer.events}"
        evt = failed_events[0]
        assert evt["exit_code"] == 137
        assert evt["oom_killed"] is True
        assert evt["memory_peak_bytes"] == 3221229568
        # The unstructured reason stays available for the long tail of
        # "something weird happened, read the blob".
        assert "exit=137" in evt["reason"]

    @pytest.mark.asyncio
    async def test_event_still_writes_when_forensic_capture_fails(self, tmp_path: Path) -> None:
        # If the inspect/cgroup reads raise, the lifecycle event must
        # still be written. The forensic fields are absent (or None)
        # rather than blocking the event.
        from agent_foundry.orchestration.container_executor import (
            ClaudeExecFailedError,
        )

        async def failing_turn(*args: Any, **kwargs: Any) -> Any:
            raise ClaudeExecFailedError(
                "claude exec failed (exit=1)",
                exit_code=1,
                output=b"",
                container_logs="",
            )

        ctx, registry, writer = _make_ctx(tmp_path=tmp_path)
        fake_mgr: FakeContainerManager = registry._manager_override  # type: ignore[assignment]

        # Make every inspect call raise. The lifecycle event must still
        # be appended.
        def _raise_inspect(*a: Any, **kw: Any) -> Any:
            raise RuntimeError("inspect broke")

        fake_mgr.inspect = _raise_inspect  # type: ignore[method-assign]

        primitive = _make_primitive()

        with pytest.raises(AgentFailedError):
            await run_agent_in_container(
                primitive=primitive,
                prompt="go",
                run_ctx=ctx,
                run_turn=failing_turn,
            )

        failed_events = [
            e for e in writer.events if e["type"] is LifecycleEvent.AGENT_INVOCATION_FAILED
        ]
        assert len(failed_events) == 1
        evt = failed_events[0]
        # reason is the load-bearing field that must always be present.
        assert "exit=1" in evt["reason"]
        # exit_code is taken from the typed exception, not from inspect,
        # so it's still available even if inspect raises.
        assert evt["exit_code"] == 1
        # oom_killed and memory_peak_bytes come from inspect/cgroup and
        # are unavailable. Either absent or None.
        assert evt.get("oom_killed") in (None, False) or "oom_killed" not in evt
        assert evt.get("memory_peak_bytes") is None or "memory_peak_bytes" not in evt


# --- inspect-container.sh auto-generation -----------------------------------
#
# When a container is retained for postmortem (pause_on_failure=True AND
# the container's invocation failed), the executor's snapshot path writes
# an inspect-container.sh helper to <run>/<agent>/ so the operator can
# `docker exec -it <id> bash` without re-deriving the user/group/cwd.


class TestInspectContainerScript:
    @pytest.mark.asyncio
    async def test_script_written_when_failed_and_pause_on_failure(self, tmp_path: Path) -> None:
        from agent_foundry.orchestration.container_executor import (
            ClaudeExecFailedError,
        )

        async def failing_turn(*args: Any, **kwargs: Any) -> Any:
            raise ClaudeExecFailedError(
                "claude exec failed (exit=137)",
                exit_code=137,
                output=b"",
                container_logs="",
            )

        ctx_default, _, _ = _make_ctx(tmp_path=tmp_path)
        ctx = ctx_default.model_copy(update={"pause_on_failure": True})

        primitive = _make_primitive()
        with pytest.raises(AgentFailedError):
            await run_agent_in_container(
                primitive=primitive,
                prompt="go",
                run_ctx=ctx,
                run_turn=failing_turn,
            )

        script_path = ctx.artifacts_dir / "test-agent" / "inspect-container.sh"
        assert script_path.exists(), f"expected inspect-container.sh at {script_path}"
        body = script_path.read_text()
        assert "docker exec" in body
        assert "fake-1" in body
        assert script_path.stat().st_mode & 0o111

    @pytest.mark.asyncio
    async def test_script_not_written_when_pause_on_failure_false(self, tmp_path: Path) -> None:
        from agent_foundry.orchestration.container_executor import (
            ClaudeExecFailedError,
        )

        async def failing_turn(*args: Any, **kwargs: Any) -> Any:
            raise ClaudeExecFailedError(
                "claude exec failed",
                exit_code=1,
                output=b"",
                container_logs="",
            )

        ctx_default, _, _ = _make_ctx(tmp_path=tmp_path)
        # Default is pause_on_failure=True; override to False for this test.
        ctx = ctx_default.model_copy(update={"pause_on_failure": False})
        primitive = _make_primitive()

        with pytest.raises(AgentFailedError):
            await run_agent_in_container(
                primitive=primitive,
                prompt="go",
                run_ctx=ctx,
                run_turn=failing_turn,
            )

        script_path = ctx.artifacts_dir / "test-agent" / "inspect-container.sh"
        assert not script_path.exists()

    @pytest.mark.asyncio
    async def test_script_not_written_on_success(self, tmp_path: Path) -> None:
        driver = FakeClaudeCodeDriver(turn_script=[_success_env()])
        ctx_default, _, _ = _make_ctx(tmp_path=tmp_path)
        ctx = ctx_default.model_copy(update={"pause_on_failure": True})

        primitive = _make_primitive()
        await run_agent_in_container(primitive=primitive, prompt="go", run_ctx=ctx, run_turn=driver)

        script_path = ctx.artifacts_dir / "test-agent" / "inspect-container.sh"
        assert not script_path.exists()
