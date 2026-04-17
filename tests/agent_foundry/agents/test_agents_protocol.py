"""Tests for Agent Container Protocol message models and parser."""

import json

import pytest

from agent_foundry.agents.errors import ProtocolError
from agent_foundry.agents.protocol import (
    AdapterMessage,
    ControlMessage,
    InputMessage,
    OutputMessage,
    StatusMessage,
    StructuredOutputMessage,
    parse_protocol_message,
)


class TestOutputMessage:
    def test_given_valid_fields_when_constructed_then_all_fields_present(self):
        msg = OutputMessage(session_id="s1", text="hello world", stream="stdout", timestamp=1.0)
        assert msg.type == "output"
        assert msg.session_id == "s1"
        assert msg.text == "hello world"
        assert msg.stream == "stdout"

    def test_given_output_message_when_stream_omitted_then_defaults_to_stdout(self):
        msg = OutputMessage(session_id="s1", text="hi", timestamp=1.0)
        assert msg.stream == "stdout"


class TestStatusMessage:
    def test_given_started_status_when_constructed_then_status_stored(self):
        msg = StatusMessage(session_id="s1", status="started", timestamp=1.0)
        assert msg.type == "status"
        assert msg.status == "started"
        assert msg.exit_code is None
        assert msg.detail == ""

    def test_given_exited_status_when_constructed_with_exit_code_then_exit_code_stored(
        self,
    ):
        msg = StatusMessage(session_id="s1", status="exited", exit_code=0, timestamp=1.0)
        assert msg.exit_code == 0

    def test_given_error_status_when_constructed_with_detail_then_detail_stored(self):
        msg = StatusMessage(
            session_id="s1",
            status="error",
            detail="timeout after 30s",
            timestamp=1.0,
        )
        assert msg.detail == "timeout after 30s"


class TestInputMessage:
    def test_given_valid_input_when_constructed_then_fields_present(self):
        msg = InputMessage(session_id="s1", text="yes\n")
        assert msg.type == "input"
        assert msg.text == "yes\n"


class TestControlMessage:
    def test_given_terminate_command_when_constructed_then_command_stored(self):
        msg = ControlMessage(session_id="s1", command="terminate")
        assert msg.type == "control"
        assert msg.command == "terminate"
        assert msg.args == {}

    def test_given_resize_command_when_constructed_with_args_then_args_stored(self):
        msg = ControlMessage(session_id="s1", command="resize", args={"rows": 24, "cols": 80})
        assert msg.args == {"rows": 24, "cols": 80}


class TestParseProtocolMessage:
    def test_given_valid_output_json_when_parsed_then_returns_output_message(self):
        data = {
            "type": "output",
            "session_id": "s1",
            "text": "hello",
            "timestamp": 1.0,
        }
        msg = parse_protocol_message(json.dumps(data))
        assert isinstance(msg, OutputMessage)
        assert msg.text == "hello"

    def test_given_valid_status_json_when_parsed_then_returns_status_message(self):
        data = {
            "type": "status",
            "session_id": "s1",
            "status": "running",
            "timestamp": 1.0,
        }
        msg = parse_protocol_message(json.dumps(data))
        assert isinstance(msg, StatusMessage)

    def test_given_valid_input_json_when_parsed_then_returns_input_message(self):
        data = {"type": "input", "session_id": "s1", "text": "go"}
        msg = parse_protocol_message(json.dumps(data))
        assert isinstance(msg, InputMessage)

    def test_given_valid_control_json_when_parsed_then_returns_control_message(self):
        data = {"type": "control", "session_id": "s1", "command": "terminate"}
        msg = parse_protocol_message(json.dumps(data))
        assert isinstance(msg, ControlMessage)

    def test_given_invalid_json_when_parsed_then_raises_protocol_error(self):
        with pytest.raises(ProtocolError, match="Invalid JSON"):
            parse_protocol_message("not json{{{")

    def test_given_missing_type_field_when_parsed_then_raises_protocol_error(self):
        with pytest.raises(ProtocolError, match="Missing 'type'"):
            parse_protocol_message(json.dumps({"session_id": "s1"}))

    def test_given_unknown_type_when_parsed_then_raises_protocol_error(self):
        with pytest.raises(ProtocolError, match="Unknown message type"):
            parse_protocol_message(json.dumps({"type": "bogus", "session_id": "s1"}))

    def test_given_adapter_message_union_when_checked_then_includes_core_types(self):
        assert OutputMessage in AdapterMessage.__args__
        assert StructuredOutputMessage in AdapterMessage.__args__
        assert StatusMessage in AdapterMessage.__args__


class TestStructuredOutputMessage:
    def test_given_valid_data_when_constructed_then_has_payload(self):
        msg = StructuredOutputMessage(
            session_id="sess-1",
            payload={"outcome": {"kind": "success", "payload": {"x": 1}}},
            timestamp=1234567890.0,
        )
        assert msg.type == "structured_output"
        assert msg.payload["outcome"]["kind"] == "success"

    def test_given_serialized_message_when_parsed_then_roundtrips(self):
        msg = StructuredOutputMessage(
            session_id="sess-1",
            payload={"outcome": {"kind": "clarification_needed", "question": "which?"}},
            timestamp=1234567890.0,
        )
        parsed = parse_protocol_message(msg.model_dump_json())
        assert isinstance(parsed, StructuredOutputMessage)
        assert parsed == msg

    def test_given_unknown_type_when_parsed_then_raises_protocol_error(self):
        with pytest.raises(ProtocolError):
            parse_protocol_message('{"type": "nonsense", "session_id": "s", "timestamp": 0}')
