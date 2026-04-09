"""Tests for Claude Code ACP adapter — marker matching and event mapping."""

import json
from typing import Any

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


class TestAdapterDetectsStructuredOutput:
    def test_given_tool_use_event_for_structured_output_then_emits_structured_output_message(self):
        adapter = ClaudeCodeAdapter()
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu-1",
                        "name": "StructuredOutput",
                        "input": {"outcome": {"kind": "success", "payload": {"city": "Paris"}}},
                    }
                ]
            },
        }
        messages, task_complete = adapter._map_event_to_protocol(event, "sess-1")
        structured = [m for m in messages if m.get("type") == "structured_output"]
        assert len(structured) == 1
        assert structured[0]["payload"] == {
            "outcome": {"kind": "success", "payload": {"city": "Paris"}}
        }
        assert task_complete is True
        # Regression guard: no generic summary output for this block
        outputs = [m for m in messages if m.get("type") == "output"]
        assert not any("StructuredOutput" in m.get("text", "") for m in outputs), (
            f"StructuredOutput block should not emit a summary output; got: {outputs}"
        )

    def test_given_tool_use_event_for_other_tool_then_no_structured_output_message(self):
        adapter = ClaudeCodeAdapter()
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu-2",
                        "name": "Read",
                        "input": {"file_path": "/tmp/foo.py"},
                    }
                ]
            },
        }
        messages, _task_complete = adapter._map_event_to_protocol(event, "sess-1")
        structured = [m for m in messages if m.get("type") == "structured_output"]
        assert len(structured) == 0
        outputs = [m for m in messages if m.get("type") == "output"]
        assert any("Read" in m.get("text", "") for m in outputs)


class TestRunTurnStructuredOutput:
    """Integration-lite test with synthetic subprocess stdout."""

    def test_given_stream_with_structured_output_tool_use_then_turn_result_populated(
        self, monkeypatch
    ):
        import subprocess

        fake_stdout_lines = [
            json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1"}) + "\n",
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu-1",
                                "name": "StructuredOutput",
                                "input": {
                                    "outcome": {
                                        "kind": "success",
                                        "payload": {"city": "Paris"},
                                    }
                                },
                            }
                        ]
                    },
                }
            )
            + "\n",
            json.dumps({"type": "result", "is_error": False, "stop_reason": "end_turn"}) + "\n",
        ]

        class _FakeProc:
            def __init__(self):
                self.stdout = iter(fake_stdout_lines)
                self.stderr = iter([])

            def wait(self):
                return 0

            def terminate(self):
                pass

        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: _FakeProc())

        class _FakeWS:
            def __init__(self):
                self.sent: list[str] = []

            def send(self, data):
                self.sent.append(data)

        adapter = ClaudeCodeAdapter()
        ws = _FakeWS()
        result = adapter.run_turn(
            prompt="test",
            ws=ws,
            protocol_session_id="proto-1",
            json_schema={
                "type": "object",
                "properties": {"outcome": {"type": "object"}},
            },
        )

        assert result.structured_output == {
            "outcome": {"kind": "success", "payload": {"city": "Paris"}}
        }
        assert result.task_complete is True
        assert result.agent_session_id == "sess-1"


class TestStderrOnError:
    def test_given_llm_error_with_stderr_then_turn_complete_carries_stderr_tail(self, monkeypatch):
        import subprocess

        fake_stdout_lines = [
            json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1"}) + "\n",
            json.dumps({"type": "result", "is_error": True, "stop_reason": "error"}) + "\n",
        ]
        fake_stderr_lines = [
            "claude: authentication failed\n",
            "hint: run `claude auth login`\n",
        ]

        class _FakeProc:
            def __init__(self):
                self.stdout = iter(fake_stdout_lines)
                self.stderr = iter(fake_stderr_lines)

            def wait(self):
                return 1

            def terminate(self):
                pass

        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: _FakeProc())

        sent: list[dict[str, Any]] = []

        class _FakeWS:
            def send(self, data):
                sent.append(json.loads(data))

        adapter = ClaudeCodeAdapter()
        adapter.run_turn(prompt="test", ws=_FakeWS(), protocol_session_id="proto-1")

        terminal = [
            m for m in sent if m.get("type") == "status" and m.get("exit_code") not in (None, 0)
        ]
        assert len(terminal) == 1, (
            f"expected exactly one terminal status; got {len(terminal)}: {terminal}"
        )
        assert "authentication failed" in terminal[0].get("detail", "")
        assert terminal[0].get("status") == "turn_complete"

    def test_given_crash_before_result_event_then_synthetic_error_status_with_stderr(
        self, monkeypatch
    ):
        import subprocess

        fake_stdout_lines = [
            json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1"}) + "\n",
        ]
        fake_stderr_lines = [
            "claude: segmentation fault\n",
            "core dumped\n",
        ]

        class _FakeProc:
            def __init__(self):
                self.stdout = iter(fake_stdout_lines)
                self.stderr = iter(fake_stderr_lines)

            def wait(self):
                return 139

            def terminate(self):
                pass

        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: _FakeProc())

        sent: list[dict[str, Any]] = []

        class _FakeWS:
            def send(self, data):
                sent.append(json.loads(data))

        adapter = ClaudeCodeAdapter()
        adapter.run_turn(prompt="test", ws=_FakeWS(), protocol_session_id="proto-1")

        terminal = [
            m for m in sent if m.get("type") == "status" and m.get("exit_code") not in (None, 0)
        ]
        assert len(terminal) == 1, (
            f"expected exactly one terminal status; got {len(terminal)}: {terminal}"
        )
        assert terminal[0].get("status") == "error"
        assert "segmentation fault" in terminal[0].get("detail", "")
        assert terminal[0].get("exit_code") == 139


class TestLocalRetryOnMissingStructuredOutput:
    def test_given_json_schema_and_no_structured_output_then_retries_once_with_resume(
        self, monkeypatch
    ):
        import subprocess

        call_count = 0

        def _fake_popen(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                stdout = [
                    json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1"})
                    + "\n",
                    json.dumps(
                        {
                            "type": "assistant",
                            "message": {
                                "content": [{"type": "text", "text": "Here is the answer."}]
                            },
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "type": "result",
                            "is_error": False,
                            "stop_reason": "end_turn",
                        }
                    )
                    + "\n",
                ]
            else:
                stdout = [
                    json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1"})
                    + "\n",
                    json.dumps(
                        {
                            "type": "assistant",
                            "message": {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tu-1",
                                        "name": "StructuredOutput",
                                        "input": {
                                            "outcome": {
                                                "kind": "success",
                                                "payload": {"x": 1},
                                            }
                                        },
                                    }
                                ]
                            },
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "type": "result",
                            "is_error": False,
                            "stop_reason": "end_turn",
                        }
                    )
                    + "\n",
                ]

            class _FakeProc:
                def __init__(self):
                    self.stdout = iter(stdout)
                    self.stderr = iter([])

                def wait(self):
                    return 0

                def terminate(self):
                    pass

            return _FakeProc()

        monkeypatch.setattr(subprocess, "Popen", _fake_popen)

        sent: list[dict[str, Any]] = []

        class _FakeWS:
            def send(self, data):
                sent.append(json.loads(data))

        adapter = ClaudeCodeAdapter()
        result = adapter.run_turn(
            prompt="test",
            ws=_FakeWS(),
            protocol_session_id="proto-1",
            json_schema={"type": "object", "properties": {"outcome": {"type": "object"}}},
        )

        assert call_count == 2
        assert result.structured_output == {"outcome": {"kind": "success", "payload": {"x": 1}}}
        assert result.task_complete is True

    def test_given_json_schema_and_no_structured_output_after_retry_then_gives_up(
        self, monkeypatch
    ):
        import subprocess

        call_count = 0

        def _fake_popen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            stdout = [
                json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1"}) + "\n",
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Still no structured output.",
                                }
                            ]
                        },
                    }
                )
                + "\n",
                json.dumps(
                    {
                        "type": "result",
                        "is_error": False,
                        "stop_reason": "end_turn",
                    }
                )
                + "\n",
            ]

            class _FakeProc:
                def __init__(self):
                    self.stdout = iter(stdout)
                    self.stderr = iter([])

                def wait(self):
                    return 0

                def terminate(self):
                    pass

            return _FakeProc()

        monkeypatch.setattr(subprocess, "Popen", _fake_popen)

        sent: list[dict[str, Any]] = []

        class _FakeWS:
            def send(self, data):
                sent.append(json.loads(data))

        adapter = ClaudeCodeAdapter()
        result = adapter.run_turn(
            prompt="test",
            ws=_FakeWS(),
            protocol_session_id="proto-1",
            json_schema={"type": "object", "properties": {"outcome": {"type": "object"}}},
        )

        assert call_count == 2
        assert result.structured_output is None
        assert result.task_complete is False

    def test_given_no_json_schema_and_no_structured_output_then_no_retry(self, monkeypatch):
        import subprocess

        call_count = 0

        def _fake_popen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            stdout = [
                json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1"}) + "\n",
                json.dumps(
                    {
                        "type": "result",
                        "is_error": False,
                        "stop_reason": "end_turn",
                    }
                )
                + "\n",
            ]

            class _FakeProc:
                def __init__(self):
                    self.stdout = iter(stdout)
                    self.stderr = iter([])

                def wait(self):
                    return 0

                def terminate(self):
                    pass

            return _FakeProc()

        monkeypatch.setattr(subprocess, "Popen", _fake_popen)

        class _FakeWS:
            def send(self, data):
                pass

        adapter = ClaudeCodeAdapter()
        adapter.run_turn(
            prompt="test",
            ws=_FakeWS(),
            protocol_session_id="proto-1",
        )

        assert call_count == 1


class TestNoRetryOnNonRecoverableStopReason:
    """When stop_reason indicates a non-recoverable condition (refusal, max_tokens),
    the adapter should NOT retry — the same prompt/limits will produce the same result.
    See: https://platform.claude.com/docs/en/build-with-claude/structured-outputs#invalid-outputs
    """

    def test_given_refusal_stop_reason_then_no_retry(self, monkeypatch):
        """Claude refused for safety reasons. Retrying is pointless."""
        import subprocess

        call_count = 0

        def _fake_popen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            stdout = [
                json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1"}) + "\n",
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {"type": "text", "text": "I cannot help with that request."}
                            ]
                        },
                    }
                )
                + "\n",
                json.dumps(
                    {
                        "type": "result",
                        "is_error": False,
                        "stop_reason": "refusal",
                    }
                )
                + "\n",
            ]

            class _FakeProc:
                def __init__(self):
                    self.stdout = iter(stdout)
                    self.stderr = iter([])

                def wait(self):
                    return 0

                def terminate(self):
                    pass

            return _FakeProc()

        monkeypatch.setattr(subprocess, "Popen", _fake_popen)

        sent = []

        class _FakeWS:
            def send(self, data):
                sent.append(json.loads(data))

        adapter = ClaudeCodeAdapter()
        result = adapter.run_turn(
            prompt="test",
            ws=_FakeWS(),
            protocol_session_id="proto-1",
            json_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
        )

        assert call_count == 1, f"expected NO retry on refusal; got {call_count} calls"
        assert result.structured_output is None

    def test_given_max_tokens_stop_reason_then_no_retry(self, monkeypatch):
        """Response was truncated. Same max_tokens = same truncation."""
        import subprocess

        call_count = 0

        def _fake_popen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            stdout = [
                json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1"}) + "\n",
                json.dumps(
                    {
                        "type": "result",
                        "is_error": False,
                        "stop_reason": "max_tokens",
                    }
                )
                + "\n",
            ]

            class _FakeProc:
                def __init__(self):
                    self.stdout = iter(stdout)
                    self.stderr = iter([])

                def wait(self):
                    return 0

                def terminate(self):
                    pass

            return _FakeProc()

        monkeypatch.setattr(subprocess, "Popen", _fake_popen)

        class _FakeWS:
            def send(self, data):
                pass

        adapter = ClaudeCodeAdapter()
        result = adapter.run_turn(
            prompt="test",
            ws=_FakeWS(),
            protocol_session_id="proto-1",
            json_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
        )

        assert call_count == 1, f"expected NO retry on max_tokens; got {call_count} calls"
        assert result.structured_output is None


class TestRetryOnRecoverableFailure:
    """Verify that retry DOES fire for recoverable failure modes — specifically
    the cold-start pattern (anthropics/claude-code#23265) where the first
    --json-schema invocation fails with is_error=True but an immediate retry
    succeeds. This is the primary bug the retry mechanism was built to catch.
    """

    def test_given_is_error_true_on_first_call_then_retries_and_succeeds(self, monkeypatch):
        """Cold-start pattern: first call fails (is_error=True), retry succeeds."""
        import subprocess

        call_count = 0

        def _fake_popen(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First call: fails with is_error=True (cold-start failure)
                stdout = [
                    json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1"})
                    + "\n",
                    json.dumps(
                        {
                            "type": "result",
                            "is_error": True,
                            "stop_reason": "error",
                        }
                    )
                    + "\n",
                ]
            else:
                # Retry: succeeds with StructuredOutput
                stdout = [
                    json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1"})
                    + "\n",
                    json.dumps(
                        {
                            "type": "assistant",
                            "message": {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tu-1",
                                        "name": "StructuredOutput",
                                        "input": {
                                            "outcome": {
                                                "kind": "success",
                                                "payload": {"value": 42},
                                            }
                                        },
                                    }
                                ]
                            },
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "type": "result",
                            "is_error": False,
                            "stop_reason": "end_turn",
                        }
                    )
                    + "\n",
                ]

            class _FakeProc:
                def __init__(self):
                    self.stdout = iter(stdout)
                    self.stderr = iter([])

                def wait(self):
                    return 1 if call_count == 1 else 0

                def terminate(self):
                    pass

            return _FakeProc()

        monkeypatch.setattr(subprocess, "Popen", _fake_popen)

        sent = []

        class _FakeWS:
            def send(self, data):
                sent.append(json.loads(data))

        adapter = ClaudeCodeAdapter()
        result = adapter.run_turn(
            prompt="test",
            ws=_FakeWS(),
            protocol_session_id="proto-1",
            json_schema={"type": "object", "properties": {"outcome": {"type": "object"}}},
        )

        assert call_count == 2, f"expected retry on is_error=True; got {call_count} calls"
        assert result.structured_output == {
            "outcome": {"kind": "success", "payload": {"value": 42}}
        }
        assert result.task_complete is True
