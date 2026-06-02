"""PrimitivePlan — top-level container for a primitive graph."""

from __future__ import annotations

from agent_foundry.primitives.models import Primitive
from agent_foundry.primitives.validators import validate_primitive


class PrimitivePlan:
    """Holds a root primitive and provides graph introspection.

    Walks the primitive graph to collect all primitives for validation,
    visualization, and compilation.
    """

    def __init__(self, root: Primitive) -> None:
        self.root = root

    def validate(self) -> None:
        """Validate type compatibility across the entire primitive graph."""
        validate_primitive(self.root)

    def all_primitives(self) -> list[Primitive]:
        """Return all primitives in the graph."""
        return self._walk(self.root)

    def _walk(self, prim: Primitive) -> list[Primitive]:
        """Recursively collect all Primitive instances in the graph."""
        result = [prim]
        for child, _ in prim.child_specs():
            result.extend(self._walk(child))
        return result
