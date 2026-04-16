"""Inner turn loop for running an AgentAction in its container (Task F.3).

Extends the E.2 scope with:
  * responder round-trip for ``ClarificationOutcome`` / ``PermissionOutcome``
  * reuse-policy dispatch across invocations (``REUSE_RESUME`` vs
    ``REUSE_NEW_SESSION``); within an invocation, continuations always
    reuse the current-turn session id
  * session-id recording on :class:`LiveContainer` via
    :meth:`AgentContainerRegistry.record_session_id`
  * lifecycle event emission: ``AGENT_INVOCATION_STARTED``,
    ``TURN_STARTED`` / ``TURN_COMPLETED``, ``RESPONDER_REQUESTED`` /
    ``RESPONDER_ANSWERED``, ``AGENT_INVOCATION_COMPLETED`` /
    ``AGENT_INVOCATION_FAILED``
  * file snapshotting on success via
    :meth:`ContainerManager.copy_from_container` into
    ``<run_dir>/<agent_name>/turns/<n>/collected_files/``
  * cancel-event check between turns
  * max 20 responder iterations per invocation

The per-turn mechanics — shelling out to ``claude`` inside the live
container via ``handle._container.exec_run`` and parsing stream-json —
live in the module-level helper :func:`_run_claude_turn`. Tests inject
a scripted fake by passing ``run_turn=<fake>`` as a keyword argument
to :func:`run_agent_in_container`; no global test seam is required.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from agent_foundry.acp.agent_turn_envelope import (
    AgentTurnEnvelope,
    ClarificationOutcome,
    PermissionOutcome,
    TurnOutcomeKind,
)
from agent_foundry.acp.schema_tools import to_claude_code_schema
from agent_foundry.models.markers import (
    FilePathFieldSpec,
    extract_paths,
    walk_file_path_fields,
)
from agent_foundry.orchestration.artifacts import agent_turn_dir
from agent_foundry.orchestration.errors import AgentFailedError
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.registry import LiveContainer
from agent_foundry.orchestration.run_context import AgentRunContext
from agent_foundry.primitives.models import (
    AgentAction,
    ContainerReusePolicy,
    get_type_args,
)
from agent_foundry.responders.models import (
    ResponderContext,
    build_request_from_outcome,
)

logger = logging.getLogger(__name__)


MAX_RESPONDER_ITERATIONS = 20


# Contract for the ``run_turn`` callable threaded through
# :func:`run_agent_in_container`. Tests inject fakes matching this
# signature via the ``run_turn=`` keyword argument.
RunTurn = Callable[
    ...,
    Awaitable[tuple[dict[str, Any], str | None]],
]


async def _run_claude_turn(
    live: LiveContainer,
    *,
    prompt: str,
    resume_session_id: str | None,
    schema: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Invoke ``claude`` once inside the live container and return the
    parsed envelope dict plus the captured session id.

    This is the production helper that :func:`run_agent_in_container`
    calls by default. It shells out via
    ``handle._container.exec_run(['claude', '-p', prompt, ...])``,
    runs the blocking call in a worker thread, and parses the
    stream-json output for:

      * the ``system/init`` event (session id)
      * the assistant ``StructuredOutput`` tool_use (envelope payload)
      * a fallback: a ```json …``` code block in an assistant text
        message, which Claude Code sometimes emits instead of the
        synthetic ``StructuredOutput`` tool call despite the
        ``--json-schema`` flag.

    Raises ``RuntimeError`` if claude exits non-zero or no envelope
    can be extracted.
    """

    def _do_exec() -> tuple[dict[str, Any], str | None]:
        cmd = [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--json-schema",
            json.dumps(schema),
        ]
        if resume_session_id:
            cmd.extend(["--resume", resume_session_id])
        exit_code, output = live.handle._container.exec_run(cmd, demux=False, user="claude")
        if exit_code != 0:
            logs = live.handle._container.logs(tail=80).decode(errors="replace")
            raise RuntimeError(
                f"claude exec failed (exit={exit_code}):\n"
                f"stdout/stderr: {output.decode(errors='replace')}\n\n"
                f"container logs: {logs}"
            )
        envelope: dict[str, Any] | None = None
        session_id: str | None = None
        fallback_texts: list[str] = []
        for raw_line in output.decode().splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("type") == "system" and evt.get("subtype") == "init":
                session_id = evt.get("session_id") or session_id
            elif evt.get("type") == "assistant":
                for block in evt.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use" and block.get("name") == "StructuredOutput":
                        envelope = block.get("input")
                    elif block.get("type") == "text":
                        fallback_texts.append(block.get("text", ""))
        # Fallback: if claude returned the envelope as a ```json …``` text
        # block rather than a ``StructuredOutput`` tool_use (which it
        # sometimes does despite the forced-tool ``--json-schema`` flag),
        # parse it out of the assistant text.
        if envelope is None and fallback_texts:
            combined = "\n".join(fallback_texts)
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", combined, flags=re.DOTALL)
            if match is not None:
                try:
                    parsed = json.loads(match.group(1))
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    if "outcome" in parsed:
                        envelope = parsed
                    else:
                        envelope = {"outcome": {"kind": "success", "payload": parsed}}
        if envelope is None:
            logs = live.handle._container.logs(tail=40).decode(errors="replace")
            raise RuntimeError(
                "no StructuredOutput tool use captured\n"
                f"--- claude stdout ({len(output)} bytes) ---\n"
                f"{output.decode(errors='replace')}\n"
                f"--- container logs ---\n{logs}"
            )
        return envelope, session_id

    return await asyncio.to_thread(_do_exec)


def _agent_name(primitive: AgentAction) -> str:
    """Return the product-declared diagnostic label for the agent.

    Used for artifact directory naming, lifecycle event payloads,
    and log prefixes. Does not participate in composition or lookup.
    """
    return primitive.name


def _snapshot_container_artifacts(
    live: LiveContainer,
    run_dir: Any,
    agent_name: str,
) -> None:
    """Persist container logs and the rendered CLAUDE.md to the host.

    Called at the end of every ``run_agent_in_container`` invocation.
    Both writes are best-effort — failures log a warning and do not
    propagate, because this runs in a ``finally`` block that must not
    shadow the primary exception (if any).

    - ``<run_dir>/<agent>/container.log`` : full container stdout +
      stderr captured so far. Overwritten each invocation; captures
      everything from container start through the most recent turn.
    - ``<run_dir>/<agent>/CLAUDE.md`` : the merged role-instructions
      file the agent actually sees (base image CLAUDE.md + appended
      role instructions). Overwritten each invocation. The content is
      ephemeral inside the container filesystem (which is destroyed at
      run teardown), so this snapshot is the only postmortem record.
    """
    from agent_foundry.orchestration.artifacts import agent_log_path

    # --- container.log ---
    try:
        inner = getattr(live.handle, "_container", None)
        logs_fn = getattr(inner, "logs", None)
        if logs_fn is not None:
            raw = logs_fn(stdout=True, stderr=True, timestamps=False)
            if isinstance(raw, bytes):
                log_path = agent_log_path(run_dir, agent_name)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_bytes(raw)
    except Exception as exc:
        logger.warning(
            "failed to snapshot container.log for agent %s: %s",
            agent_name,
            exc,
        )

    # --- CLAUDE.md ---
    try:
        manager = live.manager
        read_fn = getattr(manager, "read_file_from_container", None)
        if read_fn is not None:
            content = read_fn(live.handle, "/home/claude/.claude/CLAUDE.md")
            if isinstance(content, str):
                agent_dir = run_dir / agent_name
                agent_dir.mkdir(parents=True, exist_ok=True)
                (agent_dir / "CLAUDE.md").write_text(content, encoding="utf-8")
    except Exception as exc:
        logger.warning(
            "failed to snapshot CLAUDE.md for agent %s: %s",
            agent_name,
            exc,
        )


def _verify_paths(
    manager: Any,
    handle: Any,
    payload_dict: dict[str, Any],
    specs: list[FilePathFieldSpec],
) -> list[str]:
    violations: list[str] = []
    for path, max_size in extract_paths(payload_dict, specs):
        content = manager.read_file_from_container(handle, path)
        if content is None:
            violations.append(f"{path}: missing")
            continue
        size = len(content.encode()) if isinstance(content, str) else len(content)
        if size > max_size:
            violations.append(f"{path}: oversized ({size} > {max_size})")
    return violations


def _build_correction_prompt(violations: list[str]) -> str:
    bullets = "\n".join(f"- {v}" for v in violations)
    return (
        "You declared these files in your structured output but they are "
        "missing or oversized:\n"
        f"{bullets}\n\n"
        "Please write them correctly (or reduce their size), then emit the "
        "structured output again."
    )


async def _snapshot_files(
    *,
    live: LiveContainer,
    run_ctx: AgentRunContext,
    agent_name: str,
    turn_number: int,
    payload_dict: dict[str, Any],
    specs: list[FilePathFieldSpec],
) -> None:
    """Copy every AgentFilePath-marked field into the turn's collected_files.

    Failures are non-fatal — per the plan, verification has already
    confirmed the file exists on the container, so a copy failure is
    logged and execution continues.
    """
    if not specs:
        return
    turn_dir = agent_turn_dir(run_ctx.artifacts_dir, agent_name, turn_number)
    target_root = turn_dir / "collected_files"
    target_root.mkdir(parents=True, exist_ok=True)
    from pathlib import Path as _Path

    for declared_path, _max in extract_paths(payload_dict, specs):
        target = target_root / _Path(declared_path).name
        try:
            ok = await asyncio.to_thread(
                live.manager.copy_from_container,
                live.handle,
                declared_path,
                target,
            )
            if not ok:
                logger.warning(
                    "failed to snapshot %s from container %s",
                    declared_path,
                    getattr(live.handle, "container_id", "<unknown>"),
                )
        except Exception as exc:
            logger.warning(
                "error snapshotting %s from container %s: %s",
                declared_path,
                getattr(live.handle, "container_id", "<unknown>"),
                exc,
            )


def _initial_resume_session_id(primitive: AgentAction, live: LiveContainer) -> str | None:
    """Pick the resume session id for the first turn of this invocation.

    ``REUSE_RESUME`` threads a previously captured session id (if any)
    into ``claude --resume``. ``REUSE_NEW_SESSION`` always starts fresh.
    """
    if primitive.reuse_policy == ContainerReusePolicy.REUSE_RESUME:
        return live.session_id
    return None


async def run_agent_in_container(
    *,
    primitive: AgentAction,
    prompt: str,
    run_ctx: AgentRunContext,
    run_turn: RunTurn | None = None,
) -> BaseModel:
    """Execute one invocation of an AgentAction in its container.

    Full F.3 inner-loop semantics — see module docstring for the event
    set and retry/responder/cancel bounds.

    The ``run_turn`` kwarg is the per-turn transport: a callable matching
    the signature of :func:`_run_claude_turn`. Passing ``None`` (the
    default) resolves to the current module-level ``_run_claude_turn``
    at call time — so tests that go through the compiler (where the
    kwarg cannot be threaded) can ``monkeypatch.setattr(container_executor,
    "_run_claude_turn", fake)`` and have it take effect.
    """
    if run_turn is None:
        run_turn = _run_claude_turn
    _input_type, output_type = get_type_args(primitive)
    envelope_type = AgentTurnEnvelope[output_type]  # type: ignore[valid-type]
    schema = to_claude_code_schema(envelope_type)
    file_path_specs = walk_file_path_fields(output_type.model_json_schema())
    agent_name = _agent_name(primitive)
    registry = run_ctx.container_registry
    lifecycle = run_ctx.lifecycle_writer

    # Acquire (or create) the per-primitive live container.
    live = await registry.get_or_create(
        primitive,
        lifecycle_writer=lifecycle,
        agent_name=agent_name,
    )

    # Invocation number: best-effort counter stamped on the live container.
    invocation = (getattr(live, "_invocation_count", 0) or 0) + 1
    import contextlib

    with contextlib.suppress(Exception):
        live._invocation_count = invocation  # type: ignore[attr-defined]

    lifecycle.append(
        {
            "type": LifecycleEvent.AGENT_INVOCATION_STARTED,
            "agent_name": agent_name,
            "invocation": invocation,
        }
    )

    current_prompt = prompt
    current_resume: str | None = _initial_resume_session_id(primitive, live)
    current_session_id: str | None = live.session_id
    turn_number = 0
    responder_iterations = 0
    verification_attempts = 0

    try:
        while True:
            # Cooperative cancel between turns.
            if run_ctx.cancel_event.is_set():
                raise AgentFailedError(
                    reason="cancelled",
                    agent_name=agent_name,
                    invocation=invocation,
                )

            # Responder-loop safety cap.
            if responder_iterations > MAX_RESPONDER_ITERATIONS:
                raise AgentFailedError(
                    reason="responder loop exceeded max iterations",
                    agent_name=agent_name,
                    invocation=invocation,
                )

            lifecycle.append(
                {
                    "type": LifecycleEvent.TURN_STARTED,
                    "agent_name": agent_name,
                    "invocation": invocation,
                    "turn": turn_number,
                }
            )

            # Create the per-turn artifacts dir and persist the prompt
            # before the turn runs so a crash mid-turn still leaves a
            # readable trail.
            turn_dir = agent_turn_dir(run_ctx.artifacts_dir, agent_name, turn_number)
            try:
                (turn_dir / "prompt.txt").write_text(current_prompt, encoding="utf-8")
            except Exception:
                logger.warning("failed to persist prompt.txt for turn %s", turn_number)

            raw, captured_sid = await run_turn(
                live,
                prompt=current_prompt,
                resume_session_id=current_resume,
                schema=schema,
            )

            # Persist the raw envelope payload as soon as we have it,
            # regardless of outcome.
            try:
                import json as _json

                (turn_dir / "envelope.json").write_text(
                    _json.dumps(raw, default=str, indent=2), encoding="utf-8"
                )
            except Exception:
                logger.warning("failed to persist envelope.json for turn %s", turn_number)

            # Capture and record the session id as soon as we have one —
            # regardless of envelope outcome — so REUSE_RESUME continuations
            # (within and across invocations) have something to thread.
            if captured_sid:
                current_session_id = captured_sid
                if live.session_id != captured_sid:
                    registry.record_session_id(primitive, captured_sid)

            try:
                envelope = envelope_type.model_validate(raw)
            except ValidationError as exc:
                raise AgentFailedError(
                    reason=f"payload validation failed: {exc}",
                    agent_name=agent_name,
                    invocation=invocation,
                ) from exc

            outcome = envelope.outcome

            lifecycle.append(
                {
                    "type": LifecycleEvent.TURN_COMPLETED,
                    "agent_name": agent_name,
                    "invocation": invocation,
                    "turn": turn_number,
                    "outcome_kind": str(outcome.kind),
                }
            )

            if outcome.kind == TurnOutcomeKind.FAILED:
                lifecycle.append(
                    {
                        "type": LifecycleEvent.AGENT_INVOCATION_FAILED,
                        "agent_name": agent_name,
                        "invocation": invocation,
                        "reason": outcome.reason,
                    }
                )
                raise AgentFailedError(
                    reason=outcome.reason,
                    agent_name=agent_name,
                    invocation=invocation,
                )

            if outcome.kind == TurnOutcomeKind.SUCCESS:
                payload = outcome.payload
                payload_dict = (
                    payload.model_dump() if isinstance(payload, BaseModel) else dict(payload)
                )

                # Host-side file-path verification with one bounded retry.
                violations: list[str] = []
                if file_path_specs:
                    violations = _verify_paths(
                        live.manager, live.handle, payload_dict, file_path_specs
                    )

                if violations:
                    if verification_attempts >= 1:
                        lifecycle.append(
                            {
                                "type": LifecycleEvent.AGENT_INVOCATION_FAILED,
                                "agent_name": agent_name,
                                "invocation": invocation,
                                "reason": f"file_path_verification_failed: {violations}",
                            }
                        )
                        raise AgentFailedError(
                            reason=f"file_path_verification_failed: {violations}",
                            agent_name=agent_name,
                            invocation=invocation,
                        )
                    verification_attempts += 1
                    current_prompt = _build_correction_prompt(violations)
                    current_resume = current_session_id
                    turn_number += 1
                    continue

                # Persist the success payload as output.json.
                try:
                    import json as _json

                    (turn_dir / "output.json").write_text(
                        _json.dumps(payload_dict, default=str, indent=2),
                        encoding="utf-8",
                    )
                except Exception:
                    logger.warning("failed to persist output.json for turn %s", turn_number)

                # Success path: snapshot declared files then return.
                await _snapshot_files(
                    live=live,
                    run_ctx=run_ctx,
                    agent_name=agent_name,
                    turn_number=turn_number,
                    payload_dict=payload_dict,
                    specs=file_path_specs,
                )
                lifecycle.append(
                    {
                        "type": LifecycleEvent.AGENT_INVOCATION_COMPLETED,
                        "agent_name": agent_name,
                        "invocation": invocation,
                    }
                )
                if isinstance(payload, output_type):
                    return payload
                return output_type.model_validate(payload_dict)

            # Clarification / permission → responder round-trip.
            if outcome.kind in (
                TurnOutcomeKind.CLARIFICATION_NEEDED,
                TurnOutcomeKind.PERMISSION_NEEDED,
            ):
                provider = run_ctx.responder_provider
                if provider is None:
                    raise AgentFailedError(
                        reason=(
                            "responder required for "
                            f"{outcome.kind} outcome but run_ctx.responder_provider is None"
                        ),
                        agent_name=agent_name,
                        invocation=invocation,
                    )
                # ``outcome`` is already a ClarificationOutcome or
                # PermissionOutcome instance (discriminated union).
                assert isinstance(outcome, (ClarificationOutcome, PermissionOutcome))
                request = build_request_from_outcome(
                    outcome,
                    agent_name=agent_name,
                    invocation=invocation,
                    turn=turn_number,
                )
                responder_context = ResponderContext(
                    run_id=run_ctx.run_id,
                    request_id=uuid.uuid4().hex,
                    agent_name=agent_name,
                    invocation=invocation,
                    turn=turn_number,
                )
                lifecycle.append(
                    {
                        "type": LifecycleEvent.RESPONDER_REQUESTED,
                        "agent_name": agent_name,
                        "invocation": invocation,
                        "turn": turn_number,
                        "request_id": responder_context.request_id,
                        "kind": str(outcome.kind),
                    }
                )
                try:
                    responder = provider()
                    response = await responder.respond(request, responder_context)
                except AgentFailedError:
                    raise
                except Exception as exc:
                    lifecycle.append(
                        {
                            "type": LifecycleEvent.AGENT_INVOCATION_FAILED,
                            "agent_name": agent_name,
                            "invocation": invocation,
                            "reason": f"responder failed: {exc}",
                        }
                    )
                    raise AgentFailedError(
                        reason=f"responder failed: {exc}",
                        agent_name=agent_name,
                        invocation=invocation,
                    ) from exc

                lifecycle.append(
                    {
                        "type": LifecycleEvent.RESPONDER_ANSWERED,
                        "agent_name": agent_name,
                        "invocation": invocation,
                        "turn": turn_number,
                        "request_id": responder_context.request_id,
                    }
                )

                current_prompt = response.answer
                current_resume = current_session_id
                turn_number += 1
                responder_iterations += 1
                continue

            # Defensive: unreachable given the StrEnum covers all cases.
            raise AgentFailedError(
                reason=f"unhandled outcome kind: {outcome.kind}",
                agent_name=agent_name,
                invocation=invocation,
            )
    except AgentFailedError:
        # Already logged above at the point of raise.
        raise
    except Exception as exc:
        lifecycle.append(
            {
                "type": LifecycleEvent.AGENT_INVOCATION_FAILED,
                "agent_name": agent_name,
                "invocation": invocation,
                "reason": str(exc),
            }
        )
        raise AgentFailedError(
            reason=str(exc),
            agent_name=agent_name,
            invocation=invocation,
        ) from exc
    finally:
        # Best-effort snapshot of the container's logs + rendered
        # CLAUDE.md into the run's artifacts dir. Runs after every
        # invocation — success, failure, or cancellation — so a
        # postmortem always has both artifacts available even if the
        # agent crashed. The container filesystem is ephemeral; this
        # is the only durable record.
        _snapshot_container_artifacts(live, run_ctx.artifacts_dir, agent_name)
