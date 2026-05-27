from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_foundry.observability.models import AgentTurnRecord, StopReason, TokenUsage


def _make_record(**overrides: object) -> AgentTurnRecord:
    defaults: dict[str, object] = {
        "agent_name": "test-agent",
        "turn_index": 0,
        "started_at": datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        "ended_at": datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC),
        "duration_s": 5.0,
        "tool_calls_by_tool": {"Read": 2, "Write": 1},
        "tokens": TokenUsage(input_tokens=100, output_tokens=50),
        "subagent_spawns": 0,
        "stop_reason": StopReason.END_TURN,
        "outcome_kind": "success",
        "resume_retries": 0,
        "model": "claude-sonnet-4-6",
    }
    defaults.update(overrides)
    return AgentTurnRecord(**defaults)


class TestStopReason:
    def test_members_have_correct_string_values(self) -> None:
        assert StopReason.END_TURN == "end_turn"
        assert StopReason.MAX_TURNS == "max_turns"
        assert StopReason.TOOL_USE == "tool_use"
        assert StopReason.ERROR == "error"
        assert StopReason.UNKNOWN == "unknown"


class TestTokenUsage:
    def test_all_fields_default_to_none(self) -> None:
        usage = TokenUsage()
        assert usage.input_tokens is None
        assert usage.output_tokens is None
        assert usage.cache_read_tokens is None
        assert usage.cache_write_tokens is None

    def test_all_none_round_trips_json(self) -> None:
        usage = TokenUsage()
        restored = TokenUsage.model_validate_json(usage.model_dump_json())
        assert restored == usage
        assert restored.input_tokens is None
        assert restored.output_tokens is None
        assert restored.cache_read_tokens is None
        assert restored.cache_write_tokens is None


class TestAgentTurnRecord:
    def test_json_round_trip_is_lossless(self) -> None:
        record = _make_record()
        restored = AgentTurnRecord.model_validate_json(record.model_dump_json())
        assert restored == record

    def test_json_round_trip_preserves_datetime_with_timezone(self) -> None:
        record = _make_record()
        restored = AgentTurnRecord.model_validate_json(record.model_dump_json())
        assert restored.started_at == record.started_at
        assert restored.ended_at == record.ended_at

    def test_json_round_trip_with_all_none_tokens(self) -> None:
        record = _make_record(tokens=TokenUsage())
        restored = AgentTurnRecord.model_validate_json(record.model_dump_json())
        assert restored.tokens == TokenUsage()
        assert restored.tokens.input_tokens is None

    def test_validator_rejects_negative_turn_index(self) -> None:
        with pytest.raises(ValidationError, match="turn_index"):
            _make_record(turn_index=-1)

    def test_validator_rejects_negative_duration_s(self) -> None:
        with pytest.raises(ValidationError, match="duration_s"):
            _make_record(duration_s=-0.1)

    def test_validator_rejects_negative_resume_retries(self) -> None:
        with pytest.raises(ValidationError, match="resume_retries"):
            _make_record(resume_retries=-1)

    def test_turn_index_zero_is_valid(self) -> None:
        record = _make_record(turn_index=0)
        assert record.turn_index == 0

    def test_duration_s_zero_is_valid(self) -> None:
        record = _make_record(duration_s=0.0)
        assert record.duration_s == 0.0
