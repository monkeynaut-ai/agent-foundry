"""Strict responder for eval runs.

Single-agent eval cases must run to completion without triggering
clarification or permission interactions. If a case does trigger one,
the eval fails loudly via :class:`EvalResponderInvokedError` rather
than auto-answering — auto-answering would make outcomes
non-deterministic and obscure the variable under test.
"""

from __future__ import annotations

from agent_foundry.responders.models import (
    ResponderContext,
    ResponderRequest,
    ResponderResponse,
)
from agent_foundry.responders.protocol import Responder


class EvalResponderInvokedError(RuntimeError):
    """Raised when an agent under eval triggers a responder interaction."""


class RaiseOnInvokeResponder(Responder):
    """Responder that raises on every invocation.

    Use via :func:`agent_foundry.responders.protocol.static_provider` to
    plug into :func:`agent_foundry.orchestration.runner.run_primitive_plan`.
    """

    async def respond(
        self, request: ResponderRequest, context: ResponderContext
    ) -> ResponderResponse:
        raise EvalResponderInvokedError(
            "Responder invoked during eval — single-agent eval cases must run "
            "to completion without interactions. "
            f"agent={context.agent_name!r} invocation={context.invocation} "
            f"turn={context.turn} request_kind={request.kind}"
        )
