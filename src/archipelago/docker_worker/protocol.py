"""Protocol message models for Archipelago adapter-orchestrator communication.

Re-exports ACP protocol models. Defines Archipelago-specific marker patterns
as MarkerMapping instances. Provides backward-compatible parse_protocol_message
that accepts both old "interrupt" and new "agent_event" message types.
"""

import json
import re

from agent_foundry.acp.errors import ProtocolError
from agent_foundry.acp.protocol import (
    AdapterMessage,  # noqa: F401
    AgentEventMessage,
    ControlMessage,  # noqa: F401
    InputMessage,  # noqa: F401
    MarkerMapping,
    OrchestratorMessage,  # noqa: F401
    OutputMessage,  # noqa: F401
    ProtocolMessage,
    StatusMessage,  # noqa: F401
)
from agent_foundry.acp.protocol import parse_protocol_message as _acp_parse

# Backward compatibility alias
InterruptMessage = AgentEventMessage

# ── Archipelago-specific marker patterns ──

INTERRUPT_PATTERN = re.compile(r"^ARCHIPELAGO_NEED_(CLARIFICATION|PERMISSION)\s+(\{.*\})$")
UPDATE_PATTERN = re.compile(r"^ARCHIPELAGO_UPDATE_AVAILABLE\s+(\{.*\})$")

# MarkerMapping instances for the Claude Code adapter
ARCHIPELAGO_MARKER_MAPPINGS = [
    MarkerMapping(
        pattern=r"^ARCHIPELAGO_TASK_COMPLETE$",
        event_type="task_complete",
    ),
    MarkerMapping(
        pattern=r"^ARCHIPELAGO_NEED_CLARIFICATION\s+(\{.*\})$",
        event_type="clarification_requested",
        payload_group=1,
    ),
    MarkerMapping(
        pattern=r"^ARCHIPELAGO_NEED_PERMISSION\s+(\{.*\})$",
        event_type="permission_requested",
        payload_group=1,
    ),
    MarkerMapping(
        pattern=r"^ARCHIPELAGO_UPDATE_AVAILABLE\s+(\{.*\})$",
        event_type="update_available",
        payload_group=1,
    ),
]

# ── Backward-compatible message type mapping ──

_INTERRUPT_TYPE_MAP = {
    "clarification": "clarification_requested",
    "permission": "permission_requested",
    "update_available": "update_available",
}


def parse_protocol_message(json_str: str) -> ProtocolMessage:
    """Parse a protocol message with backward compatibility.

    Accepts both old-style {"type": "interrupt", "interrupt_type": "..."}
    and new-style {"type": "agent_event", "event_type": "..."}.
    """
    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, ValueError) as e:
        raise ProtocolError(f"Invalid JSON: {e}") from e

    # Convert old "interrupt" format to new "agent_event" format
    if data.get("type") == "interrupt":
        old_type = data.pop("interrupt_type", "unknown")
        data["type"] = "agent_event"
        data["event_type"] = _INTERRUPT_TYPE_MAP.get(old_type, old_type)

    return _acp_parse(json.dumps(data))
