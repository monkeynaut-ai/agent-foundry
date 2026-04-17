"""Orchestration error types."""

from __future__ import annotations


class AgentFailedError(RuntimeError):
    """An agent invocation terminated without producing a valid output.

    Raised when:
      - the envelope reports ``kind=failed``
      - file-path verification exhausts its one retry
      - any other non-recoverable error
    """

    def __init__(
        self,
        reason: str,
        *,
        agent_name: str | None = None,
        invocation: int | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.agent_name = agent_name
        self.invocation = invocation
