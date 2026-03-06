"""Protocol message models for adapter-orchestrator communication."""

import json
import re
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

# Interrupt marker patterns — protocol-level constants shared by adapter and detector
INTERRUPT_PATTERN = re.compile(r"^ARCHIPELAGO_NEED_(CLARIFICATION|PERMISSION)\s+(\{.*\})$")
UPDATE_PATTERN = re.compile(r"^ARCHIPELAGO_UPDATE_AVAILABLE\s+(\{.*\})$")


class ProtocolError(Exception):
    """Raised on protocol parse failures (invalid JSON, unknown type, etc.)."""


# ── Adapter-to-orchestrator messages ──


class OutputMessage(BaseModel):
    type: Literal["output"]
    session_id: str
    text: str
    stream: Literal["stdout", "stderr"] = "stdout"
    timestamp: float


class InterruptMessage(BaseModel):
    type: Literal["interrupt"]
    session_id: str
    interrupt_type: Literal["clarification", "permission", "update_available"]
    payload: dict[str, Any]
    raw_line: str
    timestamp: float


class StatusMessage(BaseModel):
    type: Literal["status"]
    session_id: str
    status: Literal["started", "running", "turn_complete", "completed", "exited", "error"]
    exit_code: int | None = None
    detail: str = ""
    timestamp: float


# ── Orchestrator-to-adapter messages ──


class InputMessage(BaseModel):
    type: Literal["input"]
    session_id: str
    text: str


class ControlMessage(BaseModel):
    type: Literal["control"]
    session_id: str
    command: Literal["resize", "terminate", "kill", "complete"]
    args: dict[str, Any] = Field(default_factory=dict)


# ── Type aliases ──

AdapterMessage = OutputMessage | InterruptMessage | StatusMessage
OrchestratorMessage = InputMessage | ControlMessage
ProtocolMessage = AdapterMessage | OrchestratorMessage

# ── Parser ──

_MESSAGE_TYPES: dict[str, type[BaseModel]] = {
    "output": OutputMessage,
    "interrupt": InterruptMessage,
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
