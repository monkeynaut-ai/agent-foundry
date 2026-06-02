"""Typed token-usage payload shared by container and AICall capture paths.

Both Claude Code container agents and Anthropic-SDK ``AICall`` agents
report token counts in the same four buckets. This model is the single
typed carrier threaded onto the ``AGENT_INVOCATION_COMPLETED`` and
``AI_CALL_COMPLETED`` lifecycle events. Every field is optional: a
source that does not report a bucket (e.g. the Anthropic SDK omits
cache counts when caching is off) leaves it ``None``, which downstream
renders as "unknown" rather than fabricating a zero.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TokenUsage(BaseModel):
    """Per-invocation token counts, one bucket per Anthropic usage field."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None

    def total_tokens(self) -> int | None:
        """Sum of all populated buckets, or ``None`` when none are populated."""
        present = [
            v
            for v in (
                self.input_tokens,
                self.output_tokens,
                self.cache_creation_input_tokens,
                self.cache_read_input_tokens,
            )
            if v is not None
        ]
        if not present:
            return None
        return sum(present)

    @classmethod
    def from_mapping(cls, raw: Any) -> TokenUsage | None:
        """Build from a usage mapping (claude ``result.usage`` shape).

        Returns ``None`` when ``raw`` is not a mapping, so a missing or
        malformed usage block degrades to "unknown" rather than crashing.
        Unknown keys are ignored; absent keys stay ``None``.
        """
        if not isinstance(raw, dict):
            return None

        def _int_or_none(value: Any) -> int | None:
            return value if isinstance(value, int) else None

        return cls(
            input_tokens=_int_or_none(raw.get("input_tokens")),
            output_tokens=_int_or_none(raw.get("output_tokens")),
            cache_creation_input_tokens=_int_or_none(raw.get("cache_creation_input_tokens")),
            cache_read_input_tokens=_int_or_none(raw.get("cache_read_input_tokens")),
        )
