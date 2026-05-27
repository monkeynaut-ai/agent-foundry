import json
from dataclasses import dataclass, field

from agent_foundry.observability.models import TokenUsage


@dataclass
class StreamMetrics:
    tool_calls_by_tool: dict[str, int] = field(default_factory=dict)
    tokens: TokenUsage = field(default_factory=TokenUsage)
    stop_reason: str | None = None
    subagent_spawns: int = 0


def extract_stream_metrics(raw: bytes) -> StreamMetrics:
    metrics = StreamMetrics()

    for raw_line in raw.splitlines():
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            continue
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type")

        if event_type == "assistant":
            content = event.get("message", {}).get("content", [])
            for item in content:
                if item.get("type") == "tool_use":
                    name: str = item.get("name", "")
                    metrics.tool_calls_by_tool[name] = metrics.tool_calls_by_tool.get(name, 0) + 1
                    if name == "Agent":
                        metrics.subagent_spawns += 1

        elif event_type == "result":
            usage = event.get("usage")
            if usage is not None:
                metrics.tokens = TokenUsage(
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    cache_read_tokens=usage.get("cache_read_input_tokens"),
                    cache_write_tokens=usage.get("cache_creation_input_tokens"),
                )
            stop_reason = event.get("stop_reason")
            if stop_reason is not None:
                metrics.stop_reason = stop_reason

    return metrics
