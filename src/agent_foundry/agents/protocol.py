"""Agent Container Protocol message models.

Defines the event vocabulary and message schemas for bidirectional
communication between containerized AI agents and their orchestrators.
"""

import json
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from agent_foundry.agents.errors import ProtocolError

# ── Agent-to-orchestrator messages ──


class OutputMessage(BaseModel):
    """Streaming text output from the agent."""

    type: Literal["output"] = "output"
    session_id: str
    text: str
    stream: Literal["stdout", "stderr"] = "stdout"
    timestamp: float


class StructuredOutputMessage(BaseModel):
    """Typed payload captured from Claude Code's StructuredOutput tool call.

    Emitted by the adapter when the agent (running under --json-schema) calls
    the synthetic StructuredOutput tool. The payload is the raw dict from
    ``tool_use.input``; orchestrators are expected to validate it against
    their own typed envelope model (e.g. ``AgentTurnEnvelope[T]``).
    """

    type: Literal["structured_output"] = "structured_output"
    session_id: str
    payload: dict[str, Any]
    timestamp: float


class StatusMessage(BaseModel):
    """Agent lifecycle status change."""

    type: Literal["status"] = "status"
    session_id: str
    status: Literal["started", "running", "turn_complete", "completed", "exited", "error"]
    exit_code: int | None = None
    detail: str = ""
    timestamp: float


# ── Orchestrator-to-agent messages ──


class InputMessage(BaseModel):
    """Text input sent to the agent (answers, approvals, instructions)."""

    type: Literal["input"] = "input"
    session_id: str
    text: str


class ControlMessage(BaseModel):
    """Control command sent to the adapter."""

    type: Literal["control"] = "control"
    session_id: str
    command: Literal["resize", "terminate", "kill", "complete"]
    args: dict[str, Any] = Field(default_factory=dict)


# ── Type aliases ──

AdapterMessage = OutputMessage | StructuredOutputMessage | StatusMessage
OrchestratorMessage = InputMessage | ControlMessage
ProtocolMessage = AdapterMessage | OrchestratorMessage

# ── Parser ──

_MESSAGE_TYPES: dict[str, type[BaseModel]] = {
    "output": OutputMessage,
    "structured_output": StructuredOutputMessage,
    "status": StatusMessage,
    "input": InputMessage,
    "control": ControlMessage,
}


def parse_protocol_message(json_str: str) -> ProtocolMessage:
    """Parse a JSON string into the correct protocol message model.

    Dispatches on the 'type' field. Raises ProtocolError for invalid JSON,
    missing type, or unknown message types.
    """
    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, ValueError) as e:
        raise ProtocolError(f"Invalid JSON: {e}") from e

    msg_type = data.get("type")
    if msg_type is None:
        raise ProtocolError("Missing 'type' field in protocol message")

    model_cls = _MESSAGE_TYPES.get(msg_type)
    if model_cls is None:
        raise ProtocolError(f"Unknown message type: {msg_type!r}")

    return cast(ProtocolMessage, model_cls.model_validate(data))
