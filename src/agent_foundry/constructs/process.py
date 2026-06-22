"""Process — top-level container for a construct graph."""

from __future__ import annotations

from agent_foundry.constructs.models import Construct
from agent_foundry.constructs.validators import validate_construct


class Process:
    """Holds a root construct and provides graph introspection.

    Walks the construct graph to collect all constructs for validation,
    visualization, and compilation.
    """

    def __init__(self, root: Construct) -> None:
        self.root = root

    def validate(self) -> None:
        """Validate type compatibility across the entire construct graph."""
        validate_construct(self.root)

    def all_constructs(self) -> list[Construct]:
        """Return all constructs in the graph."""
        return self._walk(self.root)

    def _walk(self, prim: Construct) -> list[Construct]:
        """Recursively collect all Construct instances in the graph."""
        result = [prim]
        for child, _ in prim.child_specs():
            result.extend(self._walk(child))
        return result
