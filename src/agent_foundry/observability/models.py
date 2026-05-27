from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, field_validator


class StopReason(StrEnum):
    END_TURN = "end_turn"
    MAX_TURNS = "max_turns"
    TOOL_USE = "tool_use"
    ERROR = "error"
    UNKNOWN = "unknown"


class TokenUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None


class AgentTurnRecord(BaseModel):
    agent_name: str
    turn_index: int
    started_at: datetime
    ended_at: datetime
    duration_s: float
    tool_calls_by_tool: dict[str, int]
    tokens: TokenUsage
    subagent_spawns: int
    stop_reason: StopReason
    outcome_kind: str
    resume_retries: int
    model: str

    @field_validator("turn_index")
    @classmethod
    def validate_turn_index(cls, v: int) -> int:
        if v < 0:
            raise ValueError("turn_index must be >= 0")
        return v

    @field_validator("duration_s")
    @classmethod
    def validate_duration_s(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError("duration_s must be >= 0.0")
        return v

    @field_validator("resume_retries")
    @classmethod
    def validate_resume_retries(cls, v: int) -> int:
        if v < 0:
            raise ValueError("resume_retries must be >= 0")
        return v
