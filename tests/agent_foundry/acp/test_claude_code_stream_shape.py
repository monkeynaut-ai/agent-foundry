"""Integration test: verify Claude Code's stream-json event shape.

The adapter pattern-matches on specific event types, field names, and
structure in Claude Code's ``--output-format stream-json`` output. If
Anthropic changes any of these, the adapter breaks silently. This test
runs the real ``claude`` CLI and asserts the shapes the adapter depends on.

Requires: real ``claude`` binary on PATH, active subscription, network.
Marked as integration — runs via ``pdm run test-integration``, skipped
in ``pdm run test-unit``.
"""

import json
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.integration

TRIVIAL_SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    }
)


@pytest.fixture(scope="module")
def stream_events():
    """Run claude once, parse all stream-json events, cache for the module."""
    if not shutil.which("claude"):
        pytest.skip("claude CLI not on PATH")

    result = subprocess.run(
        [
            "claude",
            "-p",
            "What is the capital of France? Answer with the city name only.",
            "--output-format",
            "stream-json",
            "--verbose",
            "--json-schema",
            TRIVIAL_SCHEMA,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        pytest.skip(f"claude exited {result.returncode}: {result.stderr[:200]}")

    events = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not events:
        pytest.skip("no stream-json events captured")

    return events


def _events_of_type(events, event_type):
    return [e for e in events if e.get("type") == event_type]


class TestSystemInitEvent:
    """Adapter depends on: event.type == 'system', event.subtype == 'init',
    event.session_id (string).
    """

    def test_system_init_event_exists(self, stream_events):
        inits = [
            e for e in stream_events if e.get("type") == "system" and e.get("subtype") == "init"
        ]
        assert len(inits) >= 1, f"no system/init event found in {len(stream_events)} events"

    def test_system_init_has_session_id(self, stream_events):
        init = next(
            e for e in stream_events if e.get("type") == "system" and e.get("subtype") == "init"
        )
        assert isinstance(init.get("session_id"), str), (
            f"session_id missing or not a string: {init}"
        )


class TestAssistantEvent:
    """Adapter depends on: event.type == 'assistant',
    event.message.content (list of blocks), block.type in ('text', 'tool_use').
    """

    def test_assistant_event_exists(self, stream_events):
        assistants = _events_of_type(stream_events, "assistant")
        assert len(assistants) >= 1

    def test_assistant_has_message_content_list(self, stream_events):
        assistant = _events_of_type(stream_events, "assistant")[0]
        content = assistant.get("message", {}).get("content")
        assert isinstance(content, list), f"content is not a list: {assistant}"

    def test_content_blocks_have_type_field(self, stream_events):
        for assistant in _events_of_type(stream_events, "assistant"):
            for block in assistant.get("message", {}).get("content", []):
                assert "type" in block, f"block missing 'type': {block}"
                assert block["type"] in ("text", "tool_use", "thinking"), (
                    f"unexpected block type: {block['type']}"
                )


class TestStructuredOutputToolUse:
    """Adapter depends on: block.type == 'tool_use', block.name == 'StructuredOutput',
    block.input (dict containing the schema-conformant payload).
    """

    def test_structured_output_tool_use_exists(self, stream_events):
        for assistant in _events_of_type(stream_events, "assistant"):
            for block in assistant.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "StructuredOutput":
                    return  # found it
        pytest.fail("no tool_use block with name='StructuredOutput' found in assistant events")

    def test_structured_output_input_is_dict(self, stream_events):
        for assistant in _events_of_type(stream_events, "assistant"):
            for block in assistant.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "StructuredOutput":
                    assert isinstance(block.get("input"), dict), (
                        f"StructuredOutput input is not a dict: {block}"
                    )
                    return
        pytest.fail("StructuredOutput block not found")

    def test_structured_output_payload_matches_schema(self, stream_events):
        for assistant in _events_of_type(stream_events, "assistant"):
            for block in assistant.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "StructuredOutput":
                    payload = block["input"]
                    assert "city" in payload, f"payload missing 'city': {payload}"
                    assert isinstance(payload["city"], str), f"city is not a string: {payload}"
                    return
        pytest.fail("StructuredOutput block not found")


class TestResultEvent:
    """Adapter depends on: event.type == 'result', event.is_error (bool),
    event.stop_reason (string).
    """

    def test_result_event_exists(self, stream_events):
        results = _events_of_type(stream_events, "result")
        assert len(results) >= 1

    def test_result_has_is_error_bool(self, stream_events):
        result = _events_of_type(stream_events, "result")[-1]
        assert isinstance(result.get("is_error"), bool), f"is_error missing or not bool: {result}"

    def test_result_has_stop_reason_string(self, stream_events):
        result = _events_of_type(stream_events, "result")[-1]
        assert isinstance(result.get("stop_reason"), str), (
            f"stop_reason missing or not string: {result}"
        )

    def test_result_has_structured_output(self, stream_events):
        """The final result event should carry the structured_output field
        when --json-schema is used."""
        result = _events_of_type(stream_events, "result")[-1]
        assert "structured_output" in result, (
            f"structured_output field missing from result event: {list(result.keys())}"
        )
        assert isinstance(result["structured_output"], dict), (
            f"structured_output is not a dict: {result['structured_output']}"
        )
