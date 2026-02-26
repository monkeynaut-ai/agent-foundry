"""Execution tracer: captures spans per node with timestamps and metadata."""

import time
from dataclasses import dataclass, field
from typing import Any

FF_TRACING = True
FF_TRACE_TOOL_IO = True
FF_TRACE_RETRIEVAL = True

# Keys that should be redacted in tool call args
_SENSITIVE_KEYS = {"api_key", "secret", "password", "token", "authorization"}


@dataclass
class Span:
    """A trace span for a single node execution."""

    node_id: str
    capability: str
    start_time: float = 0.0
    end_time: float = 0.0
    status: str = "pending"
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    retrieval_info: dict[str, Any] | None = None


class ExecutionTracer:
    """Collects execution spans for observability."""

    def __init__(self):
        self._spans: list[Span] = []

    @property
    def spans(self) -> list[Span]:
        return list(self._spans)

    def start_span(self, node_id: str, capability: str) -> Span:
        span = Span(
            node_id=node_id,
            capability=capability,
            start_time=time.time(),
        )
        self._spans.append(span)
        return span

    def end_span(self, span: Span, status: str) -> None:
        span.end_time = time.time()
        span.status = status

    def add_tool_call(
        self,
        span: Span,
        tool_name: str,
        args: dict[str, Any],
        result: Any,
    ) -> None:
        redacted_args = _redact_sensitive(args)
        span.tool_calls.append({
            "tool_name": tool_name,
            "args": redacted_args,
            "result": result,
        })

    def add_retrieval(
        self,
        span: Span,
        snippet_ids: list[str],
        ranks: list[int],
    ) -> None:
        span.retrieval_info = {
            "snippet_ids": snippet_ids,
            "ranks": ranks,
        }

    def export(self) -> list[dict[str, Any]]:
        return [
            {
                "node_id": s.node_id,
                "capability": s.capability,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "status": s.status,
                "tool_calls": s.tool_calls,
                "retrieval_info": s.retrieval_info,
            }
            for s in self._spans
        ]


def _redact_sensitive(data: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in data.items():
        if key.lower() in _SENSITIVE_KEYS:
            result[key] = "[REDACTED]"
        elif isinstance(value, dict):
            result[key] = _redact_sensitive(value)
        else:
            result[key] = value
    return result
