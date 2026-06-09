"""``runtime.responder()`` resolves the run's responder, or None outside a run."""

from __future__ import annotations

import asyncio

from agent_foundry import runtime
from agent_foundry.orchestration.lifecycle_writer import NoOpLifecycleWriter
from agent_foundry.orchestration.run_context import RunContext, current_run_context
from agent_foundry.responders.models import (
    ClarificationRequest,
    ResponderContext,
    ResponderRequest,
    ResponderResponse,
)
from agent_foundry.responders.protocol import Responder, static_provider


class _EchoResponder(Responder):
    async def respond(
        self, request: ResponderRequest, context: ResponderContext
    ) -> ResponderResponse:
        return ResponderResponse(answer="echo")


def _ctx(tmp_path, provider) -> RunContext:
    return RunContext(
        run_id="resp-test",
        artifacts_dir=tmp_path,
        container_registry=object(),
        responder_provider=provider,
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={},
    )


def test_responder_returns_none_outside_run():
    assert runtime.responder() is None


def test_responder_returns_resolved_responder_inside_run(tmp_path):
    resp = _EchoResponder()
    ctx = _ctx(tmp_path, static_provider(resp))
    token = current_run_context.set(ctx)
    try:
        assert runtime.responder() is resp
    finally:
        current_run_context.reset(token)


def test_responder_returns_none_when_provider_unset(tmp_path):
    ctx = _ctx(tmp_path, None)
    token = current_run_context.set(ctx)
    try:
        assert runtime.responder() is None
    finally:
        current_run_context.reset(token)


def test_responder_is_exported():
    assert "responder" in runtime.__all__


def test_responder_is_awaitable_from_async_context(tmp_path):
    resp = _EchoResponder()
    ctx = _ctx(tmp_path, static_provider(resp))

    async def use_it() -> str:
        r = runtime.responder()
        assert r is not None
        request = ClarificationRequest(question="pick", agent_name="a", invocation=0, turn=0)
        rctx = ResponderContext(
            run_id="resp-test",
            request_id="rid",
            agent_name="a",
            invocation=0,
            turn=0,
        )
        out = await r.respond(request, rctx)
        return out.answer

    token = current_run_context.set(ctx)
    try:
        assert asyncio.run(use_it()) == "echo"
    finally:
        current_run_context.reset(token)
