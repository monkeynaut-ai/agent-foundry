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

Tests inject a scripted ``FakeClaudeCodeDriver`` via the module-level
``set_driver_factory`` seam. The production factory (not wired here)
lives in :mod:`agent_foundry.orchestration.claude_cmd` and shells out
to ``handle._container.exec_run``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import Any, Protocol

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


class Driver(Protocol):
    async def run_turn(
        self, *, prompt: str, resume_session_id: str | None
    ) -> tuple[dict[str, Any], str | None]: ...


DriverFactory = Callable[[LiveContainer, dict[str, Any]], Driver]


_DEFAULT_DRIVER_FACTORY: DriverFactory | None = None


def set_driver_factory(factory: DriverFactory | None) -> None:
    """Test hook — replace the production driver factory with a fake.

    Production default (``None``) will use the ``ExecRunDriver`` once
    that lands in :mod:`agent_foundry.orchestration.claude_cmd`. Tests
    call this with a lambda returning a scripted
    :class:`FakeClaudeCodeDriver` and reset with ``None`` in teardown.
    """
    global _DEFAULT_DRIVER_FACTORY
    _DEFAULT_DRIVER_FACTORY = factory


def build_adapter(live: LiveContainer) -> Any:
    """Legacy seam preserved for F0-era tests.

    Production wiring now flows through :func:`set_driver_factory`.
    F0.5's `_HostDrivenAdapter` (integration test) still patches this
    symbol to drop in a host-driven driver for a real container.
    """
    raise NotImplementedError(
        "Production driver wiring is installed via set_driver_factory. "
        "Tests may also monkeypatch container_executor.build_adapter for "
        "the legacy seam (returns a Driver-shaped object)."
    )


def _resolve_driver(live: LiveContainer, schema: dict[str, Any]) -> Driver:
    """Pick a driver instance for this invocation.

    Order of precedence:
      1. ``_DEFAULT_DRIVER_FACTORY`` installed via
         :func:`set_driver_factory` (new F.3 seam, and what the F.3
         tests wire).
      2. ``build_adapter(live)`` if the F0/F0.5 monkeypatch path has
         swapped in something callable (legacy seam).
    """
    if _DEFAULT_DRIVER_FACTORY is not None:
        return _DEFAULT_DRIVER_FACTORY(live, schema)
    # Fall back to the legacy build_adapter path. If the caller has not
    # monkeypatched it, this will raise NotImplementedError.
    return build_adapter(live)  # type: ignore[return-value]


def _agent_name(primitive: AgentAction) -> str:
    return getattr(primitive, "__name__", None) or type(primitive).__name__


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
) -> BaseModel:
    """Execute one invocation of an AgentAction in its container.

    Full F.3 inner-loop semantics — see module docstring for the event
    set and retry/responder/cancel bounds.
    """
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

    driver = _resolve_driver(live, schema)

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

            raw, captured_sid = await driver.run_turn(
                prompt=current_prompt,
                resume_session_id=current_resume,
            )

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
