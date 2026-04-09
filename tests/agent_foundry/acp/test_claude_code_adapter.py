"""Tests for Claude Code ACP adapter — marker matching and event mapping."""

import json

from agent_foundry.acp.adapters.claude_code import ClaudeCodeAdapter, _build_claude_cmd
from agent_foundry.acp.protocol import MarkerMapping


def _make_adapter(mappings=None):
    if mappings is None:
        mappings = [
            MarkerMapping(pattern=r"^TASK_DONE$", event_type="task_complete"),
            MarkerMapping(
                pattern=r"^NEED_HELP\s+(\{.*\})$",
                event_type="clarification_requested",
                payload_group=1,
            ),
            MarkerMapping(
                pattern=r"^NEED_PERM\s+(\{.*\})$",
                event_type="permission_requested",
                payload_group=1,
            ),
        ]
    return ClaudeCodeAdapter(marker_mappings=mappings)


class TestBuildClaudeCmd:
    def test_given_prompt_when_built_then_includes_headless_flags(self):
        cmd = _build_claude_cmd("do something")
        assert "claude" in cmd
        assert "-p" in cmd
        assert "--output-format" in cmd
        assert "stream-json" in cmd
        assert "--verbose" in cmd

    def test_given_session_id_when_built_then_includes_resume(self):
        cmd = _build_claude_cmd("prompt", session_id="sess-1")
        assert "--resume" in cmd
        assert "sess-1" in cmd

    def test_given_skip_permissions_when_built_then_includes_flag(self):
        cmd = _build_claude_cmd("prompt", skip_permissions=True)
        assert "--dangerously-skip-permissions" in cmd


class TestMarkerMatching:
    def test_given_task_complete_marker_when_matched_then_returns_event_type(self):
        adapter = _make_adapter()
        result = adapter._match_marker("TASK_DONE")
        assert result is not None
        event_type, payload = result
        assert event_type == "task_complete"
        assert payload == {}

    def test_given_clarification_marker_with_payload_when_matched_then_returns_payload(self):
        adapter = _make_adapter()
        result = adapter._match_marker('NEED_HELP {"question": "which branch?"}')
        assert result is not None
        event_type, payload = result
        assert event_type == "clarification_requested"
        assert payload["question"] == "which branch?"

    def test_given_non_marker_line_when_matched_then_returns_none(self):
        adapter = _make_adapter()
        assert adapter._match_marker("just regular output") is None

    def test_given_marker_with_bad_json_when_matched_then_returns_none(self):
        adapter = _make_adapter()
        assert adapter._match_marker("NEED_HELP {bad json}") is None

    def test_given_no_mappings_when_matched_then_always_none(self):
        adapter = ClaudeCodeAdapter(marker_mappings=[])
        assert adapter._match_marker("TASK_DONE") is None


class TestEventMapping:
    def test_given_assistant_text_with_task_complete_when_mapped_then_task_complete_true(self):
        adapter = _make_adapter()
        event = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "All done.\nTASK_DONE"}]},
        }
        msgs, tc = adapter._map_event_to_protocol(event, "s1")
        assert tc is True
        # "All done." should still appear as output
        output_msgs = [m for m in msgs if m["type"] == "output"]
        assert any("All done." in m["text"] for m in output_msgs)

    def test_given_assistant_text_with_interrupt_when_mapped_then_agent_event_emitted(self):
        adapter = _make_adapter()
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": 'NEED_HELP {"question": "which?", "options": ["a", "b"]}',
                    }
                ]
            },
        }
        msgs, tc = adapter._map_event_to_protocol(event, "s1")
        assert tc is False
        event_msgs = [m for m in msgs if m["type"] == "agent_event"]
        assert len(event_msgs) == 1
        assert event_msgs[0]["event_type"] == "clarification_requested"
        assert event_msgs[0]["payload"]["question"] == "which?"

    def test_given_plain_text_when_mapped_then_output_message_emitted(self):
        adapter = _make_adapter()
        event = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Working on it..."}]},
        }
        msgs, tc = adapter._map_event_to_protocol(event, "s1")
        assert tc is False
        assert len(msgs) == 1
        assert msgs[0]["type"] == "output"
        assert msgs[0]["text"] == "Working on it..."

    def test_given_result_event_when_mapped_then_turn_complete_status_emitted(self):
        adapter = _make_adapter()
        event = {"type": "result", "is_error": False, "stop_reason": "end_turn"}
        msgs, tc = adapter._map_event_to_protocol(event, "s1")
        assert tc is False
        assert len(msgs) == 1
        assert msgs[0]["type"] == "status"
        assert msgs[0]["status"] == "turn_complete"
        assert msgs[0]["exit_code"] == 0

    def test_given_error_event_when_mapped_then_stderr_output_emitted(self):
        adapter = _make_adapter()
        event = {"type": "error", "error": {"message": "rate limited"}}
        msgs, _tc = adapter._map_event_to_protocol(event, "s1")
        assert len(msgs) == 1
        assert msgs[0]["stream"] == "stderr"
        assert "rate limited" in msgs[0]["text"]

    def test_given_tool_use_block_when_mapped_then_tool_summary_emitted(self):
        adapter = _make_adapter()
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "pytest -v"},
                    }
                ]
            },
        }
        msgs, _tc = adapter._map_event_to_protocol(event, "s1")
        assert len(msgs) == 1
        assert "[tool_use: Bash] pytest -v" in msgs[0]["text"]


class TestAdapterConfig:
    def test_given_custom_mappings_when_constructed_then_compiled(self):
        adapter = ClaudeCodeAdapter(
            marker_mappings=[
                MarkerMapping(pattern=r"^CUSTOM_DONE$", event_type="task_complete"),
            ]
        )
        assert len(adapter._compiled_markers) == 1

    def test_given_skip_permissions_when_constructed_then_stored(self):
        adapter = ClaudeCodeAdapter(skip_permissions=True)
        assert adapter._skip_permissions is True

    def test_given_timeouts_when_constructed_then_stored(self):
        adapter = ClaudeCodeAdapter(turn_timeout=120.0, connect_timeout=10.0)
        assert adapter._turn_timeout == 120.0
        assert adapter._connect_timeout == 10.0


class TestBuildClaudeCmdJsonSchema:
    def test_given_no_schema_when_cmd_built_then_no_json_schema_flag(self):
        cmd = _build_claude_cmd("hello", json_schema=None)
        assert "--json-schema" not in cmd

    def test_given_schema_when_cmd_built_then_json_schema_flag_emitted(self):
        schema = {"type": "object", "properties": {"city": {"type": "string"}}}
        cmd = _build_claude_cmd("hello", json_schema=schema)
        assert "--json-schema" in cmd
        idx = cmd.index("--json-schema")
        assert json.loads(cmd[idx + 1]) == schema

    def test_given_schema_and_session_id_when_cmd_built_then_both_flags_present(self):
        schema = {"type": "object"}
        cmd = _build_claude_cmd("hello", session_id="sess-1", json_schema=schema)
        assert "--json-schema" in cmd
        assert "--resume" in cmd
