"""Retry policy for resilient inference.

Declares how many times to retry a *transient* failure against the same model
before failing over to the next model in the chain. Failover targets live on
the model (``ModelEntry.fallback``); this governs only the per-model retry
loop.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RetryPolicy(BaseModel):
    """How to retry a single model on transient errors.

    ``max_attempts`` is the total number of tries for one model (1 = no retry).
    Backoff between tries is exponential: ``backoff_base_seconds * 2**(n-1)``,
    capped at ``backoff_max_seconds``.
    """

    max_attempts: int = Field(default=3, ge=1)
    backoff_base_seconds: float = Field(default=0.5, ge=0.0)
    backoff_max_seconds: float = Field(default=8.0, ge=0.0)

    def backoff_for(self, attempt: int) -> float:
        """Seconds to wait before the next try, given the just-failed ``attempt`` (1-based)."""
        return min(self.backoff_max_seconds, self.backoff_base_seconds * (2 ** (attempt - 1)))


# Platform default applied when an AICall declares no retry override.
DEFAULT_RETRY_POLICY = RetryPolicy()
