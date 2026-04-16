"""Responder contract and provider helpers.

:class:`Responder` is an abstract base class — product code that
implements the contract declares inheritance explicitly so the
relationship is visible to LSP navigation and enforced at
instantiation time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from agent_foundry.responders.models import (
    ResponderContext,
    ResponderRequest,
    ResponderResponse,
)


class Responder(ABC):
    """Abstract contract for human-in-the-loop responders.

    Concrete implementations must implement :meth:`respond` to answer
    clarification and permission requests raised by agents.
    """

    @abstractmethod
    async def respond(
        self, request: ResponderRequest, context: ResponderContext
    ) -> ResponderResponse:
        """Return a :class:`ResponderResponse` for ``request``."""


ResponderProvider = Callable[[], Responder]


def static_provider(responder: Responder) -> ResponderProvider:
    """Return a provider that always resolves to the given responder."""
    return lambda: responder
