"""Responder protocol and provider helpers (CS7 Plan 2)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from agent_foundry.responders.models import (
    ResponderContext,
    ResponderRequest,
    ResponderResponse,
)


@runtime_checkable
class Responder(Protocol):
    async def respond(
        self, request: ResponderRequest, context: ResponderContext
    ) -> ResponderResponse: ...


ResponderProvider = Callable[[], Responder]


def static_provider(responder: Responder) -> ResponderProvider:
    """Return a provider that always resolves to the given responder."""
    return lambda: responder
