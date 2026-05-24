"""Tests for ``RaiseOnInvokeResponder`` in ``agent_foundry.evals.tasks``."""

from __future__ import annotations

import pytest

from agent_foundry.evals.agent_foundry_tasks import (
    EvalResponderInvokedError,
    RaiseOnInvokeResponder,
)
from agent_foundry.responders.models import (
    ClarificationRequest,
    ResponderContext,
)
from agent_foundry.responders.protocol import Responder


def test_raise_on_invoke_responder_is_a_responder() -> None:
    """Should subclass Responder so it can be used with static_provider()."""
    responder = RaiseOnInvokeResponder()
    assert isinstance(responder, Responder)


@pytest.mark.asyncio
async def test_raise_on_invoke_responder_raises_on_respond() -> None:
    """Single-agent eval must not trigger interactions; respond() must raise."""
    responder = RaiseOnInvokeResponder()
    request = ClarificationRequest(
        question="What now?",
        options=["yes", "no"],
        agent_name="agent",
        invocation=1,
        turn=1,
    )
    context = ResponderContext(
        run_id="run",
        request_id="req",
        agent_name="agent",
        invocation=1,
        turn=1,
    )
    with pytest.raises(EvalResponderInvokedError):
        await responder.respond(request, context)


@pytest.mark.asyncio
async def test_error_message_identifies_eval_context() -> None:
    """The error should make the eval context obvious to whoever reads the log."""
    responder = RaiseOnInvokeResponder()
    request = ClarificationRequest(
        question="?",
        agent_name="agent",
        invocation=1,
        turn=1,
    )
    context = ResponderContext(
        run_id="run",
        request_id="req",
        agent_name="agent",
        invocation=1,
        turn=1,
    )
    with pytest.raises(EvalResponderInvokedError) as exc_info:
        await responder.respond(request, context)
    msg = str(exc_info.value).lower()
    assert "eval" in msg
