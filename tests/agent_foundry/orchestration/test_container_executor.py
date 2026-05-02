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
) -> AgentAction:
    return AgentAction[InputModel, output_type](  # type: ignore[valid-type]
        name="test-agent",
        prompt_builder=lambda s: f"do: {s.task}",
        instructions_provider=lambda _s: "Be precise.",
        executor=run_agent_in_container,
        reuse_policy=reuse_policy,
        skip_permissions=skip_permissions,
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
    snapshot = ctx.artifacts_dir / agent_name / "turns" / "0" / "collected_files" / "out.txt"
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
        "claude",
        "-p",
        "go",
        "--output-format",
        "stream-json",
        "--verbose",
        "--json-schema",
        "{}",
    )
    fake_mgr.exec_script[cmd] = _ExecResult(exit_code=0, output=_stream_lines(init_evt, asst_evt))

    result = await _run_claude_turn(live, prompt="go", resume_session_id=None, schema={})
    assert result.envelope == payload
    assert result.session_id == "sess-z"


@pytest.mark.asyncio
async def test_run_claude_turn_raises_on_nonzero_exit_with_log_tail() -> None:
    fake_mgr = FakeContainerManager()
    live, _ = _make_live_with_fake_mgr(fake_mgr)
    cmd = (
        "claude",
        "-p",
        "go",
        "--output-format",
        "stream-json",
        "--verbose",
        "--json-schema",
        "{}",
    )
    fake_mgr.exec_script[cmd] = _ExecResult(exit_code=2, output=b"boom-stderr")
    fake_mgr.logs_script[live.handle.container_id] = b"recent log line\n"

    with pytest.raises(RuntimeError, match="claude exec failed"):
        await _run_claude_turn(live, prompt="go", resume_session_id=None, schema={})
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
        "claude",
        "-p",
        "go",
        "--output-format",
        "stream-json",
        "--verbose",
        "--json-schema",
        "{}",
    )
    # No assistant tool_use, no fallback text: just init.
    init_evt = {"type": "system", "subtype": "init", "session_id": "sess-x"}
    fake_mgr.exec_script[cmd] = _ExecResult(exit_code=0, output=_stream_lines(init_evt))

    with pytest.raises(RuntimeError, match="no StructuredOutput"):
        await _run_claude_turn(live, prompt="go", resume_session_id=None, schema={})


@pytest.mark.asyncio
async def test_run_claude_turn_falls_back_to_json_text_block() -> None:
    """Claude sometimes emits the envelope as a ```json …``` text block
    rather than a StructuredOutput tool_use, despite --json-schema."""
    fake_mgr = FakeContainerManager()
    live, _ = _make_live_with_fake_mgr(fake_mgr)
    cmd = (
        "claude",
        "-p",
        "go",
        "--output-format",
        "stream-json",
        "--verbose",
        "--json-schema",
        "{}",
    )
    init_evt = {"type": "system", "subtype": "init", "session_id": "sess-fb"}
    text = '```json\n{"outcome": {"kind": "success", "payload": {"answer": "fb"}}}\n```'
    asst_evt = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }
    fake_mgr.exec_script[cmd] = _ExecResult(exit_code=0, output=_stream_lines(init_evt, asst_evt))

    result = await _run_claude_turn(live, prompt="go", resume_session_id=None, schema={})
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
                live, prompt="go", resume_session_id=None, schema={}, skip_permissions=False
            )

        cmd = fake_mgr.exec_calls[0]["cmd"]
        assert "--dangerously-skip-permissions" not in cmd

    @pytest.mark.asyncio
    async def test_given_skip_permissions_true_then_dangerous_flag_present(self) -> None:
        fake_mgr = FakeContainerManager()
        live, _ = _make_live_with_fake_mgr(fake_mgr)

        with pytest.raises(RuntimeError):
            await _run_claude_turn(
                live, prompt="go", resume_session_id=None, schema={}, skip_permissions=True
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
