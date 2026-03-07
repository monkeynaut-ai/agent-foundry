"""Protocol message models — unit tests for adapter-orchestrator communication."""

import json

import pytest
from pydantic import ValidationError

from archipelago.docker_worker.protocol import (
    ControlMessage,
    InputMessage,
    InterruptMessage,
    OutputMessage,
    ProtocolError,
    StatusMessage,
    parse_protocol_message,
)


class TestOutputMessage:
    def test_given_valid_fields_when_instantiated_then_validates(self):
        msg = OutputMessage(
            type="output",
            session_id="s1",
            text="Running pytest... 5 passed",
            stream="stdout",
            timestamp=1709654321.123,
        )
        assert msg.type == "output"
        assert msg.session_id == "s1"
        assert msg.text == "Running pytest... 5 passed"
        assert msg.stream == "stdout"
        assert msg.timestamp == 1709654321.123

    def test_given_valid_instance_when_json_round_tripped_then_no_field_loss(self):
        msg = OutputMessage(
            type="output",
            session_id="s1",
            text="hello",
            stream="stderr",
            timestamp=1.0,
        )
        json_str = msg.model_dump_json()
        restored = OutputMessage.model_validate_json(json_str)
        assert restored == msg

    def test_given_invalid_type_when_instantiated_then_raises_validation_error(self):
        with pytest.raises(ValidationError):
            OutputMessage(
                type="wrong",
                session_id="s1",
                text="hello",
                timestamp=1.0,
            )


class TestInterruptMessage:
    def test_given_clarification_payload_when_instantiated_then_validates(self):
        msg = InterruptMessage(
            type="interrupt",
            session_id="s1",
            interrupt_type="clarification",
            payload={"question": "Which DB?", "options": ["pg"], "default": "pg", "blocking": True},
            raw_line='ARCHIPELAGO_NEED_CLARIFICATION {"question":"Which DB?"}',
            timestamp=1.0,
        )
        assert msg.interrupt_type == "clarification"
        assert msg.payload["question"] == "Which DB?"

    def test_given_permission_payload_when_instantiated_then_validates(self):
        msg = InterruptMessage(
            type="interrupt",
            session_id="s1",
            interrupt_type="permission",
            payload={"action": "delete file", "risk_level": "high", "why_needed": "cleanup"},
            raw_line="ARCHIPELAGO_NEED_PERMISSION ...",
            timestamp=1.0,
        )
        assert msg.interrupt_type == "permission"

    def test_given_update_available_payload_when_instantiated_then_validates(self):
        msg = InterruptMessage(
            type="interrupt",
            session_id="s1",
            interrupt_type="update_available",
            payload={"installed": "1.0.0", "latest": "1.1.0"},
            raw_line="ARCHIPELAGO_UPDATE_AVAILABLE ...",
            timestamp=1.0,
        )
        assert msg.interrupt_type == "update_available"

    def test_given_valid_instance_when_json_round_tripped_then_no_field_loss(self):
        msg = InterruptMessage(
            type="interrupt",
            session_id="s1",
            interrupt_type="clarification",
            payload={"question": "Which DB?", "options": ["pg"]},
            raw_line="raw",
            timestamp=2.5,
        )
        json_str = msg.model_dump_json()
        restored = InterruptMessage.model_validate_json(json_str)
        assert restored == msg


class TestStatusMessage:
    def test_given_exited_status_with_exit_code_when_instantiated_then_validates(self):
        msg = StatusMessage(
            type="status",
            session_id="s1",
            status="exited",
            exit_code=0,
            detail="Process exited normally",
            timestamp=1.0,
        )
        assert msg.status == "exited"
        assert msg.exit_code == 0

    def test_given_started_status_when_instantiated_then_exit_code_is_none(self):
        msg = StatusMessage(
            type="status",
            session_id="s1",
            status="started",
            timestamp=1.0,
        )
        assert msg.exit_code is None
        assert msg.detail == ""

    def test_given_invalid_status_value_when_instantiated_then_raises_validation_error(self):
        with pytest.raises(ValidationError):
            StatusMessage(
                type="status",
                session_id="s1",
                status="bogus",
                timestamp=1.0,
            )


class TestInputMessage:
    def test_given_valid_fields_when_instantiated_then_validates(self):
        msg = InputMessage(
            type="input",
            session_id="s1",
            text="pg\n",
        )
        assert msg.type == "input"
        assert msg.text == "pg\n"

    def test_given_valid_instance_when_json_round_tripped_then_no_field_loss(self):
        msg = InputMessage(type="input", session_id="s1", text="hello\n")
        json_str = msg.model_dump_json()
        restored = InputMessage.model_validate_json(json_str)
        assert restored == msg


class TestControlMessage:
    def test_given_resize_command_when_instantiated_then_validates(self):
        msg = ControlMessage(
            type="control",
            session_id="s1",
            command="resize",
            args={"rows": 50, "cols": 120},
        )
        assert msg.command == "resize"
        assert msg.args["rows"] == 50

    def test_given_terminate_command_when_instantiated_then_validates(self):
        msg = ControlMessage(
            type="control",
            session_id="s1",
            command="terminate",
        )
        assert msg.command == "terminate"
        assert msg.args == {}

    def test_given_invalid_command_when_instantiated_then_raises_validation_error(self):
        with pytest.raises(ValidationError):
            ControlMessage(
                type="control",
                session_id="s1",
                command="reboot",
            )


class TestParseProtocolMessage:
    def test_given_output_json_when_parsed_then_returns_output_message(self):
        data = json.dumps(
            {
                "type": "output",
                "session_id": "s1",
                "text": "hi",
                "stream": "stdout",
                "timestamp": 1.0,
            }
        )
        msg = parse_protocol_message(data)
        assert isinstance(msg, OutputMessage)
        assert msg.text == "hi"

    def test_given_interrupt_json_when_parsed_then_returns_interrupt_message(self):
        data = json.dumps(
            {
                "type": "interrupt",
                "session_id": "s1",
                "interrupt_type": "clarification",
                "payload": {"question": "Which DB?"},
                "raw_line": "raw",
                "timestamp": 1.0,
            }
        )
        msg = parse_protocol_message(data)
        assert isinstance(msg, InterruptMessage)

    def test_given_status_json_when_parsed_then_returns_status_message(self):
        data = json.dumps(
            {
                "type": "status",
                "session_id": "s1",
                "status": "exited",
                "exit_code": 0,
                "timestamp": 1.0,
            }
        )
        msg = parse_protocol_message(data)
        assert isinstance(msg, StatusMessage)
        assert msg.exit_code == 0

    def test_given_input_json_when_parsed_then_returns_input_message(self):
        data = json.dumps(
            {
                "type": "input",
                "session_id": "s1",
                "text": "pg\n",
            }
        )
        msg = parse_protocol_message(data)
        assert isinstance(msg, InputMessage)

    def test_given_control_json_when_parsed_then_returns_control_message(self):
        data = json.dumps(
            {
                "type": "control",
                "session_id": "s1",
                "command": "resize",
                "args": {"rows": 50, "cols": 120},
            }
        )
        msg = parse_protocol_message(data)
        assert isinstance(msg, ControlMessage)

    def test_given_unknown_type_when_parsed_then_raises_protocol_error(self):
        data = json.dumps({"type": "unknown", "session_id": "s1"})
        with pytest.raises(ProtocolError, match="Unknown message type"):
            parse_protocol_message(data)

    def test_given_invalid_json_when_parsed_then_raises_protocol_error(self):
        with pytest.raises(ProtocolError, match="Invalid JSON"):
            parse_protocol_message("not json {{{")

    def test_given_missing_type_field_when_parsed_then_raises_protocol_error(self):
        data = json.dumps({"session_id": "s1", "text": "hello"})
        with pytest.raises(ProtocolError, match="Missing 'type' field"):
            parse_protocol_message(data)
