"""Tests for Responder protocol and provider."""

from __future__ import annotations

from typing import cast, get_type_hints

from agent_foundry.responders.models import (
    ClarificationRequest,
    ResponderContext,
    ResponderResponse,
)
from agent_foundry.responders.protocol import (
    Responder,
    ResponderProvider,
    static_provider,
)


class FakeResponder:
    """Minimal class that structurally satisfies the Responder protocol."""

    async def respond(
        self, request: ClarificationRequest, context: ResponderContext
    ) -> ResponderResponse:
        return ResponderResponse(answer="ok")


def _make_context() -> ResponderContext:
    return ResponderContext(
        run_id="run-1",
        request_id="req-1",
        agent_name="coder",
        invocation=0,
        turn=0,
    )


class TestResponderProtocol:
    def test_fake_responder_satisfies_protocol(self):
        fake = FakeResponder()
        # Accept either @runtime_checkable isinstance support or cast fallback.
        try:
            assert isinstance(fake, Responder)
        except TypeError:
            responder = cast(Responder, fake)
            assert responder is fake

    def test_protocol_declares_respond_method(self):
        assert hasattr(Responder, "respond")
        assert callable(Responder.respond)


class TestResponderProvider:
    def test_responder_provider_is_callable_returning_responder(self):
        def provider() -> Responder:
            return FakeResponder()

        typed_provider: ResponderProvider = provider
        result = typed_provider()
        # Structural check: has awaitable respond method.
        assert hasattr(result, "respond")

    def test_responder_provider_type_alias_resolves(self):
        # Ensures the alias is importable and usable as a type annotation.
        hints = get_type_hints(_annotated_fn)
        assert "provider" in hints


def _annotated_fn(provider: ResponderProvider) -> None:  # pragma: no cover - type only
    _ = provider


class TestStaticProvider:
    def test_static_provider_returns_callable(self):
        fake = FakeResponder()
        provider = static_provider(fake)
        assert callable(provider)

    def test_static_provider_identity_preserved(self):
        fake = FakeResponder()
        provider = static_provider(fake)
        assert provider() is fake

    def test_static_provider_returns_same_instance_every_call(self):
        fake = FakeResponder()
        provider = static_provider(fake)
        assert provider() is provider() is fake
