"""Typed models for Claude Code's stream-json event shape.

These models are the single source of truth for every structural assumption
the adapter makes about Claude Code's output. If Anthropic changes the event
shape, update these models — the adapter and the integration test both derive
from them, so a change here propagates automatically.

Parse raw JSON dicts into typed events at the boundary (the ``for line in
proc.stdout`` loop in ``run_turn``) via ``parse_stream_event``. Everything
downstream works with typed objects — no scattered ``event.get("type")``
or ``block.get("name")`` calls.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ── Event models ──


class SystemInitEvent(BaseModel, extra="ignore"):
    """First event in a stream — carries the session ID."""

    type: Literal["system"]
    subtype: Literal["init"]
    session_id: str


class TextBlock(BaseModel, extra="ignore"):
    type: Literal["text"]
    text: str


class ToolUseBlock(BaseModel, extra="ignore"):
    type: Literal["tool_use"]
    id: str = ""
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


# Content blocks use Pydantic's smart-union matching on the `type` field.
# Not a discriminated union because we want graceful fallback for unknown
# block types (handled by the adapter's content-loop, not the model).
ContentBlock = TextBlock | ToolUseBlock


class AssistantMessage(BaseModel, extra="ignore"):
    content: list[ContentBlock] = Field(default_factory=list)


class AssistantEvent(BaseModel, extra="ignore"):
    """Agent response — contains text and/or tool_use blocks."""

    type: Literal["assistant"]
    message: AssistantMessage


class ResultEvent(BaseModel, extra="ignore"):
    """Terminal event — signals turn completion."""

    type: Literal["result"]
    is_error: bool = False
    stop_reason: str = ""
    structured_output: dict[str, Any] | None = None


class ErrorDetail(BaseModel, extra="ignore"):
    message: str = "unknown error"


class ErrorEvent(BaseModel, extra="ignore"):
    """Error event — usually rate limits or API errors."""

    type: Literal["error"]
    error: ErrorDetail


# ── Union of all known event types ──

ClaudeStreamEvent = SystemInitEvent | AssistantEvent | ResultEvent | ErrorEvent

# ── Constants the adapter depends on ──

STRUCTURED_OUTPUT_TOOL_NAME = "StructuredOutput"
NON_RECOVERABLE_STOP_REASONS = frozenset({"refusal", "max_tokens"})


# ── Parser ──


def parse_stream_event(raw: dict[str, Any]) -> ClaudeStreamEvent | None:
    """Parse a raw stream-json dict into a typed event model.

    Returns None for unknown or irrelevant event types (rate_limit_event,
    user synthetic messages, system events other than init, etc.). The
    adapter skips these.
    """
    event_type = raw.get("type")

    if event_type == "system" and raw.get("subtype") == "init":
        return SystemInitEvent.model_validate(raw)
    if event_type == "assistant":
        return AssistantEvent.model_validate(raw)
    if event_type == "result":
        return ResultEvent.model_validate(raw)
    if event_type == "error":
        return ErrorEvent.model_validate(raw)

    return None
