import json

from agent_foundry.observability.models import TokenUsage
from agent_foundry.observability.stream_metrics import extract_stream_metrics


def _encode(events: list[dict]) -> bytes:
    return "\n".join(json.dumps(e) for e in events).encode("utf-8")


class TestExtractStreamMetrics:
    def test_single_assistant_event_counts_tool_calls(self) -> None:
        raw = _encode(
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": "Read"},
                            {"type": "tool_use", "name": "Read"},
                            {"type": "tool_use", "name": "Write"},
                        ]
                    },
                }
            ]
        )
        metrics = extract_stream_metrics(raw)
        assert metrics.tool_calls_by_tool == {"Read": 2, "Write": 1}

    def test_multiple_assistant_events_accumulate_tool_calls(self) -> None:
        raw = _encode(
            [
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Read"}]},
                },
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": "Read"},
                            {"type": "tool_use", "name": "Edit"},
                        ]
                    },
                },
            ]
        )
        metrics = extract_stream_metrics(raw)
        assert metrics.tool_calls_by_tool == {"Read": 2, "Edit": 1}

    def test_result_event_with_usage_populates_token_fields(self) -> None:
        raw = _encode(
            [
                {
                    "type": "result",
                    "usage": {
                        "input_tokens": 200,
                        "output_tokens": 100,
                        "cache_read_input_tokens": 50,
                        "cache_creation_input_tokens": 10,
                    },
                    "stop_reason": "end_turn",
                }
            ]
        )
        metrics = extract_stream_metrics(raw)
        assert metrics.tokens.input_tokens == 200
        assert metrics.tokens.output_tokens == 100
        assert metrics.tokens.cache_read_tokens == 50
        assert metrics.tokens.cache_write_tokens == 10

    def test_result_event_without_usage_key_leaves_tokens_all_none(self) -> None:
        raw = _encode([{"type": "result", "stop_reason": "end_turn"}])
        metrics = extract_stream_metrics(raw)
        assert metrics.tokens == TokenUsage()
        assert metrics.tokens.input_tokens is None
        assert metrics.tokens.output_tokens is None

    def test_agent_tool_use_increments_subagent_spawns(self) -> None:
        raw = _encode(
            [
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Agent"}]},
                }
            ]
        )
        metrics = extract_stream_metrics(raw)
        assert metrics.subagent_spawns == 1
        assert metrics.tool_calls_by_tool["Agent"] == 1

    def test_multiple_agent_tool_uses_accumulate_spawns(self) -> None:
        raw = _encode(
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": "Agent"},
                            {"type": "tool_use", "name": "Agent"},
                        ]
                    },
                }
            ]
        )
        metrics = extract_stream_metrics(raw)
        assert metrics.subagent_spawns == 2
        assert metrics.tool_calls_by_tool["Agent"] == 2

    def test_result_event_stop_reason_captured(self) -> None:
        raw = _encode([{"type": "result", "stop_reason": "end_turn"}])
        metrics = extract_stream_metrics(raw)
        assert metrics.stop_reason == "end_turn"

    def test_empty_bytes_returns_default_stream_metrics(self) -> None:
        metrics = extract_stream_metrics(b"")
        assert metrics.tool_calls_by_tool == {}
        assert metrics.tokens == TokenUsage()
        assert metrics.stop_reason is None
        assert metrics.subagent_spawns == 0

    def test_malformed_lines_skipped_valid_lines_still_processed(self) -> None:
        raw = b"not json\n" + json.dumps({"type": "result", "stop_reason": "max_turns"}).encode()
        metrics = extract_stream_metrics(raw)
        assert metrics.stop_reason == "max_turns"
