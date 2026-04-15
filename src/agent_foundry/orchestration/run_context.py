"""Minimal AgentRunContext for Phase F0.

Phase B (Task B.1) replaces this with the full context carrying
artifacts_dir, responder_provider, cancel_event, and a real
LifecycleWriter. F0 only needs enough context to stand up a
container and run one turn.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class LifecycleWriter(Protocol):
    def append(self, event: dict[str, Any]) -> None: ...


class NoOpLifecycleWriter:
    """Satisfies the LifecycleWriter protocol by discarding all events.

    Phase B Task B.2 introduces the real append-only jsonl writer.
    """

    def append(self, event: dict[str, Any]) -> None:
        return None


class AgentRunContext(BaseModel):
    """Minimum-viable run context for the F0 executor.

    Fields:
      - run_id: unique identifier for this run
      - container_registry: AgentContainerRegistry (duck-typed in F0)
      - lifecycle_writer: any object satisfying LifecycleWriter protocol
      - env: container env dict (must include CLAUDE_CODE_OAUTH_TOKEN)
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    container_registry: Any
    lifecycle_writer: Any
    env: dict[str, str]
