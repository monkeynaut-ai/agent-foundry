"""Tests for Claude Code stream-json event models.

These models are the single source of truth for what the adapter expects
from Claude Code's output. If Claude Code changes its event shape, these
models (and only these models) need updating.
"""

from agent_foundry.agents.claude_code_events import (
    AssistantEvent,
    ErrorEvent,
    ResultEvent,
    SystemInitEvent,
    TextBlock,
    ToolUseBlock,
    parse_stream_event,
)


class TestSystemInitEvent:
    def test_given_valid_init_event_when_parsed_then_session_id_captured(self):
        raw = {"type": "system", "subtype": "init", "session_id": "sess-1"}
        event = SystemInitEvent.model_validate(raw)
        assert event.session_id == "sess-1"

    def test_given_extra_fields_when_parsed_then_ignored(self):
        raw = {
            "type": "system",
            "subtype": "init",
            "session_id": "sess-1",
            "tools": ["Bash", "Read"],
            "model": "claude-opus-4-6",
        }
        event = SystemInitEvent.model_validate(raw)
        assert event.session_id == "sess-1"


class TestAssistantEvent:
    def test_given_text_block_when_parsed_then_text_accessible(self):
        raw = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Hello world"}]},
        }
        event = AssistantEvent.model_validate(raw)
        assert len(event.message.content) == 1
        block = event.message.content[0]
        assert isinstance(block, TextBlock)
        assert block.text == "Hello world"

    def test_given_tool_use_block_when_parsed_then_name_and_input_accessible(self):
        raw = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu-1",
                        "name": "StructuredOutput",
                        "input": {"outcome": {"kind": "success"}},
                    }
                ]
            },
        }
        event = AssistantEvent.model_validate(raw)
        block = event.message.content[0]
        assert isinstance(block, ToolUseBlock)
        assert block.name == "StructuredOutput"
        assert block.input == {"outcome": {"kind": "success"}}

    def test_given_mixed_blocks_when_parsed_then_both_types_preserved(self):
        raw = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "thinking..."},
                    {
                        "type": "tool_use",
                        "id": "tu-1",
                        "name": "Bash",
                        "input": {"command": "ls"},
                    },
                ]
            },
        }
        event = AssistantEvent.model_validate(raw)
        assert len(event.message.content) == 2
        assert isinstance(event.message.content[0], TextBlock)
        assert isinstance(event.message.content[1], ToolUseBlock)

    def test_given_empty_content_when_parsed_then_empty_list(self):
        raw = {"type": "assistant", "message": {"content": []}}
        event = AssistantEvent.model_validate(raw)
        assert event.message.content == []


class TestResultEvent:
    def test_given_success_result_when_parsed_then_fields_accessible(self):
        raw = {
            "type": "result",
            "is_error": False,
            "stop_reason": "end_turn",
            "structured_output": {"city": "Paris"},
        }
        event = ResultEvent.model_validate(raw)
        assert event.is_error is False
        assert event.stop_reason == "end_turn"
        assert event.structured_output == {"city": "Paris"}

    def test_given_error_result_when_parsed_then_is_error_true(self):
        raw = {"type": "result", "is_error": True, "stop_reason": "error"}
        event = ResultEvent.model_validate(raw)
        assert event.is_error is True

    def test_given_no_structured_output_when_parsed_then_none(self):
        raw = {"type": "result", "is_error": False, "stop_reason": "end_turn"}
        event = ResultEvent.model_validate(raw)
        assert event.structured_output is None

    def test_given_extra_fields_when_parsed_then_ignored(self):
        raw = {
            "type": "result",
            "is_error": False,
            "stop_reason": "end_turn",
            "duration_ms": 1234,
            "total_cost_usd": 0.05,
        }
        event = ResultEvent.model_validate(raw)
        assert event.stop_reason == "end_turn"


class TestErrorEvent:
    def test_given_error_event_when_parsed_then_message_accessible(self):
        raw = {"type": "error", "error": {"message": "rate limited"}}
        event = ErrorEvent.model_validate(raw)
        assert event.error.message == "rate limited"

    def test_given_missing_message_when_parsed_then_default(self):
        raw = {"type": "error", "error": {}}
        event = ErrorEvent.model_validate(raw)
        assert event.error.message == "unknown error"


class TestParseStreamEvent:
    def test_given_system_init_when_dispatched_then_returns_typed(self):
        raw = {"type": "system", "subtype": "init", "session_id": "s1"}
        event = parse_stream_event(raw)
        assert isinstance(event, SystemInitEvent)

    def test_given_assistant_when_dispatched_then_returns_typed(self):
        raw = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "hi"}]},
        }
        event = parse_stream_event(raw)
        assert isinstance(event, AssistantEvent)

    def test_given_result_when_dispatched_then_returns_typed(self):
        raw = {"type": "result", "is_error": False, "stop_reason": "end_turn"}
        event = parse_stream_event(raw)
        assert isinstance(event, ResultEvent)

    def test_given_error_when_dispatched_then_returns_typed(self):
        raw = {"type": "error", "error": {"message": "boom"}}
        event = parse_stream_event(raw)
        assert isinstance(event, ErrorEvent)

    def test_given_unknown_type_when_dispatched_then_returns_none(self):
        raw = {"type": "rate_limit_event", "rate_limit_info": {}}
        assert parse_stream_event(raw) is None

    def test_given_system_non_init_when_dispatched_then_returns_none(self):
        raw = {"type": "system", "subtype": "other", "data": {}}
        assert parse_stream_event(raw) is None

    def test_given_user_synthetic_when_dispatched_then_returns_none(self):
        raw = {"type": "user", "message": {"content": [{"type": "text", "text": "..."}]}}
        assert parse_stream_event(raw) is None
