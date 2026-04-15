"""Minimum viable run_agent_in_container (Phase F0).

One turn, success-only, no reuse, no responders, no artifacts.
Phases F.1 through F.4 replace this with the full inner-loop executor.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from agent_foundry.acp.agent_turn_envelope import AgentTurnEnvelope, TurnOutcomeKind
from agent_foundry.acp.schema_tools import to_claude_code_schema
from agent_foundry.orchestration.registry import LiveContainer
from agent_foundry.orchestration.run_context import AgentRunContext
from agent_foundry.primitives.models import AgentAction, get_type_args


def build_adapter(live: LiveContainer) -> Any:
    """Construct the real claude-code driver bound to a container.

    F0 stub — the production driver (``ExecRunDriver``) lands in
    Phase F.3 in ``orchestration/claude_cmd.py`` and wraps
    ``handle._container.exec_run``. Tests monkeypatch this symbol.

    The F0 end-to-end integration test (``test_f0_agent_action_end_to_end.py``)
    injects a real host-driven driver via the same monkeypatch seam so
    this stub does not need to know about real Claude Code.
    """
    raise NotImplementedError(
        "Production driver wiring lands in Phase F.3 as "
        "orchestration.claude_cmd.ExecRunDriver; F0 tests must "
        "monkeypatch container_executor.build_adapter."
    )


async def run_agent_in_container(
    *,
    primitive: AgentAction,
    prompt: str,
    run_ctx: AgentRunContext,
) -> BaseModel:
    """F0 executor: single turn, success-only, no reuse.

    1. Build AgentTurnEnvelope[O] schema.
    2. Get instructions via primitive.instructions_provider().
    3. Create a fresh container via run_ctx.container_registry.
    4. Run one turn via the adapter.
    5. Validate success payload against O and return.
    6. Destroy the container in finally.
    """
    _input_type, output_type = get_type_args(primitive)
    envelope_type = AgentTurnEnvelope[output_type]  # type: ignore[valid-type]
    schema = to_claude_code_schema(envelope_type)
    instructions_text = primitive.instructions_provider()

    oauth_token = run_ctx.env["CLAUDE_CODE_OAUTH_TOKEN"]
    registry = run_ctx.container_registry
    live = await registry.create_for_invocation(
        primitive,
        oauth_token=oauth_token,
        instructions_text=instructions_text,
    )
    try:
        adapter = build_adapter(live)
        raw = await adapter.run_turn(
            prompt=prompt,
            json_schema=schema,
            resume_session_id=None,
        )
        envelope = envelope_type.model_validate(raw)
        outcome = envelope.outcome
        if outcome.kind != TurnOutcomeKind.SUCCESS:
            raise NotImplementedError(
                "F0 handles success only; clarification / permission / "
                "failure outcomes land in Phase F.3."
            )
        payload = outcome.payload
        if isinstance(payload, output_type):
            return payload
        return output_type.model_validate(
            payload.model_dump() if isinstance(payload, BaseModel) else payload
        )
    finally:
        await registry.destroy(live)
