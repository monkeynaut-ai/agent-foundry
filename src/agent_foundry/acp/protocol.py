"""Agent Container Protocol message models.

Defines the event vocabulary and message schemas for bidirectional
communication between containerized AI agents and their orchestrators.
"""

import json
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from agent_foundry.acp.errors import ProtocolError

# ── Agent-to-orchestrator messages ──


class OutputMessage(BaseModel):
    """Streaming text output from the agent."""

    type: Literal["output"] = "output"
    session_id: str
    text: str
    stream: Literal["stdout", "stderr"] = "stdout"
    timestamp: float


class AgentEventMessage(BaseModel):
    """Structured event emitted by the agent (detected via marker mapping).

    Replaces the Archipelago-specific InterruptMessage with a generic
    event vocabulary usable by any containerized agent.
    """

    type: Literal["agent_event"] = "agent_event"
    session_id: str
    # ACP vocabulary: task_complete, clarification_requested, permission_requested, stuck, etc.
    event_type: str
    payload: dict[str, Any]
    raw_line: str  # original marker line for audit
    timestamp: float


class StructuredOutputMessage(BaseModel):
    """Typed payload captured from Claude Code's StructuredOutput tool call.

    Emitted by the adapter when the agent (running under --json-schema) calls
    the synthetic StructuredOutput tool. The payload is the raw dict from
    ``tool_use.input``; orchestrators are expected to validate it against
    their own typed envelope model.

    Distinct from AgentEventMessage: this carries the turn's final typed
    result, not a mid-stream signal parsed from free text.
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


# ── Marker mapping ──


class MarkerMapping(BaseModel):
    """Maps a product-defined marker pattern to an ACP event type.

    The adapter uses these to translate raw agent stdout into structured
    AgentEventMessage instances.

    Attributes:
        pattern: Regex pattern to match against agent output lines.
        event_type: ACP event type to emit when the pattern matches.
        payload_group: Regex group index containing a JSON payload (if any).
    """

    pattern: str
    event_type: str
    payload_group: int | None = None


# ── Type aliases ──

AdapterMessage = OutputMessage | AgentEventMessage | StructuredOutputMessage | StatusMessage
OrchestratorMessage = InputMessage | ControlMessage
ProtocolMessage = AdapterMessage | OrchestratorMessage

# ── Parser ──

_MESSAGE_TYPES: dict[str, type[BaseModel]] = {
    "output": OutputMessage,
    "agent_event": AgentEventMessage,
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
