"""Abstract adapter interface for Agent Container Protocol.

An adapter is the in-container bridge between an AI agent CLI and
the ACP WebSocket protocol. Each agent type (Claude Code, Codex, etc.)
has its own adapter implementation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TurnResult:
    """Result of a single agent turn.

    Attributes:
        agent_session_id: Agent's internal session ID (for --resume).
        exit_code: Agent CLI exit code for this turn.
        task_complete: Whether the agent signaled task completion.
    """

    agent_session_id: str | None = None
    exit_code: int = -1
    task_complete: bool = False


class AdapterBase(ABC):
    """Abstract base for ACP adapters.

    Subclasses implement the bridge between a specific AI agent CLI
    and the ACP WebSocket protocol.
    """

    @abstractmethod
    def run_turn(
        self,
        prompt: str,
        ws: Any,
        protocol_session_id: str,
        **kwargs: Any,
    ) -> TurnResult:
        """Run a single agent turn.

        Args:
            prompt: Text prompt to send to the agent.
            ws: WebSocket connection for sending protocol messages.
            protocol_session_id: ACP session ID.

        Returns:
            TurnResult with agent session ID, exit code, and completion status.
        """

    @abstractmethod
    def run(
        self,
        initial_prompt: str | None,
        ws_url: str,
        protocol_session_id: str,
        **kwargs: Any,
    ) -> int:
        """Run the full adapter loop (connect, turns, shutdown).

        Args:
            initial_prompt: Optional initial prompt text.
            ws_url: WebSocket URL to connect to.
            protocol_session_id: ACP session ID.

        Returns:
            Exit code (0 = success).
        """
