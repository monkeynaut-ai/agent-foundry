"""Registry for ``AICall`` instances eligible for evaluation.

An application's opt-in surface for Agent Foundry's eval system.
Use the ``register`` method to register each AICall object you
want evaluated.
"""

from __future__ import annotations

from collections.abc import Iterator

from agent_foundry.primitives.ai_call import AICall


class DuplicateAICallError(ValueError):
    """Raised when registering an AICall under a name already in use."""


class UnknownAICallError(KeyError):
    """Raised when looking up an AICall name that was never registered."""


class AICallRegistry:
    """Name → AICall mapping populated by app code at startup.

    Names must be unique within a registry. Lookups are by exact name;
    no fallback or fuzzy match. Unknown names raise loudly.
    """

    def __init__(self) -> None:
        self._items: dict[str, AICall] = {}

    def register(self, name: str, call: AICall) -> None:
        """Register ``call`` under ``name``.

        Raises :class:`DuplicateAICallError` if ``name`` is already
        registered — silent overwrite is rejected.
        """
        if name in self._items:
            raise DuplicateAICallError(f"AICall already registered under name: {name!r}")
        self._items[name] = call

    def get(self, name: str) -> AICall:
        """Return the AICall registered under ``name``.

        Raises :class:`UnknownAICallError` if no registration matches.
        """
        if name not in self._items:
            raise UnknownAICallError(f"No AICall registered under name: {name!r}")
        return self._items[name]

    def names(self) -> list[str]:
        """Return the registered names."""
        return list(self._items)

    def __iter__(self) -> Iterator[tuple[str, AICall]]:
        return iter(self._items.items())

    def __contains__(self, name: object) -> bool:
        return name in self._items

    def __len__(self) -> int:
        return len(self._items)
