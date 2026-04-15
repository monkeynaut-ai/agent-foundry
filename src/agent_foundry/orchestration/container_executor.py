"""run_agent_in_container with host-side file-path verification (Task E.2).

F0 handled a single success-only turn. E.2 extends that with:
  * post-success file-path verification via
    :func:`agent_foundry.models.markers.extract_paths` +
    :meth:`ContainerManager.read_file_from_container`;
  * one bounded ``--resume`` correction turn on verification failure;
  * :class:`AgentFailedError` on ``FailureOutcome`` envelopes and on
    exhausted verification retries.

Clarification / permission outcomes still raise ``NotImplementedError``
until Task F.3 wires responder handling.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from agent_foundry.acp.agent_turn_envelope import AgentTurnEnvelope, TurnOutcomeKind
from agent_foundry.acp.schema_tools import to_claude_code_schema
from agent_foundry.models.markers import (
    FilePathFieldSpec,
    extract_paths,
    walk_file_path_fields,
)
from agent_foundry.orchestration.errors import AgentFailedError
from agent_foundry.orchestration.registry import LiveContainer
from agent_foundry.orchestration.run_context import AgentRunContext
from agent_foundry.primitives.models import AgentAction, get_type_args


def build_adapter(live: LiveContainer) -> Any:
    """Construct the real claude-code driver bound to a container.

    F0 stub — the production driver (``ExecRunDriver``) lands in
    Phase F.3 in ``orchestration/claude_cmd.py`` and wraps
    ``handle._container.exec_run``. Tests monkeypatch this symbol.
    """
    raise NotImplementedError(
        "Production driver wiring lands in Phase F.3 as "
        "orchestration.claude_cmd.ExecRunDriver; tests must "
        "monkeypatch container_executor.build_adapter."
    )


def _verify_paths(
    manager: Any,
    handle: Any,
    payload_dict: dict[str, Any],
    specs: list[FilePathFieldSpec],
) -> list[str]:
    """Return human-readable violation strings for declared file paths.

    Empty list means verification passed. Each violation describes one
    missing or oversized file so the correction prompt can name it.
    """
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


async def run_agent_in_container(
    *,
    primitive: AgentAction,
    prompt: str,
    run_ctx: AgentRunContext,
) -> BaseModel:
    """Executor with host-side file-path verification and bounded retry.

    Flow per invocation:
      1. Build envelope schema + extract file-path field specs from O.
      2. Create a fresh container and an adapter bound to it.
      3. Run the initial turn; on SuccessOutcome, verify declared file
         paths; on violation, issue one ``--resume`` correction turn.
      4. On FailureOutcome, raise :class:`AgentFailedError`.
      5. Destroy the container in the ``finally`` clause.
    """
    _input_type, output_type = get_type_args(primitive)
    envelope_type = AgentTurnEnvelope[output_type]  # type: ignore[valid-type]
    schema = to_claude_code_schema(envelope_type)
    file_path_specs = walk_file_path_fields(output_type.model_json_schema())
    instructions_text = primitive.instructions_provider()

    oauth_token = run_ctx.env["CLAUDE_CODE_OAUTH_TOKEN"]
    registry = run_ctx.container_registry
    live = await registry.create_for_invocation(
        primitive,
        oauth_token=oauth_token,
        instructions_text=instructions_text,
    )
    agent_name = getattr(primitive, "__name__", None) or type(primitive).__name__
    try:
        adapter = build_adapter(live)

        current_prompt = prompt
        current_resume: str | None = None
        attempt = 0
        while True:
            attempt += 1
            raw = await adapter.run_turn(
                prompt=current_prompt,
                json_schema=schema,
                resume_session_id=current_resume,
            )

            # Surface a session id for any subsequent --resume turn. Prefer
            # whatever the adapter put on the raw envelope; fall back to the
            # container id so the retry path is always a resumed turn.
            surfaced_session = None
            if isinstance(raw, dict):
                maybe_sid = raw.get("session_id")
                if isinstance(maybe_sid, str) and maybe_sid:
                    surfaced_session = maybe_sid
            if surfaced_session is None:
                surfaced_session = live.handle.container_id

            envelope = envelope_type.model_validate(raw)
            outcome = envelope.outcome

            if outcome.kind == TurnOutcomeKind.FAILED:
                raise AgentFailedError(
                    reason=outcome.reason,
                    agent_name=agent_name,
                    invocation=attempt,
                )
            if outcome.kind != TurnOutcomeKind.SUCCESS:
                raise NotImplementedError("Clarification / permission outcomes land in Phase F.3.")

            payload = outcome.payload
            payload_dict = payload.model_dump() if isinstance(payload, BaseModel) else dict(payload)

            violations: list[str] = []
            if file_path_specs:
                violations = _verify_paths(live.manager, live.handle, payload_dict, file_path_specs)

            if not violations:
                if isinstance(payload, output_type):
                    return payload
                return output_type.model_validate(payload_dict)

            if attempt >= 2:
                raise AgentFailedError(
                    reason=f"file_path_verification_failed: {violations}",
                    agent_name=agent_name,
                    invocation=attempt,
                )

            # Bounded retry: one --resume correction turn.
            current_prompt = _build_correction_prompt(violations)
            current_resume = surfaced_session
    finally:
        await registry.destroy(live)
