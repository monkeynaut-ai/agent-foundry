import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from agent_foundry.observability.models import AgentTurnRecord, StopReason, TokenUsage
from agent_foundry.observability.store import NoOpObservabilityStore, ObservabilityStore
from agent_foundry.observability.summary import summarize_run


class _ListStore(ObservabilityStore):
    def __init__(self, records: list[AgentTurnRecord]) -> None:
        self._records = records

    def append(self, record: AgentTurnRecord) -> None:
        self._records.append(record)

    def iter_records(self) -> Iterator[AgentTurnRecord]:
        return iter(self._records)

    def close(self) -> None:
        pass


def _record(
    *,
    agent_name: str = "agent-a",
    turn_index: int = 0,
    duration_s: float = 1.0,
    tool_calls_by_tool: dict[str, int] | None = None,
    tokens: TokenUsage | None = None,
    outcome_kind: str = "success",
) -> AgentTurnRecord:
    return AgentTurnRecord(
        agent_name=agent_name,
        turn_index=turn_index,
        started_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        ended_at=datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC),
        duration_s=duration_s,
        tool_calls_by_tool=tool_calls_by_tool or {},
        tokens=tokens or TokenUsage(),
        subagent_spawns=0,
        stop_reason=StopReason.END_TURN,
        outcome_kind=outcome_kind,
        resume_retries=0,
        model="claude-sonnet-4-6",
    )


class TestSummarizeRunEmpty:
    def test_empty_store_returns_zero_totals(self) -> None:
        result = summarize_run(NoOpObservabilityStore())
        assert result.turn_count == 0
        assert result.total_duration_s == 0.0
        assert result.tool_calls_by_tool == {}
        assert result.tokens == TokenUsage()
        assert result.agents == []


class TestSummarizeRunSingleAgent:
    def test_single_turn_produces_correct_summary(self) -> None:
        record = _record(
            agent_name="agent-a",
            turn_index=0,
            duration_s=2.5,
            tool_calls_by_tool={"Bash": 3},
            tokens=TokenUsage(input_tokens=100, output_tokens=50),
            outcome_kind="success",
        )
        result = summarize_run(_ListStore([record]))

        assert result.turn_count == 1
        assert result.total_duration_s == 2.5
        assert result.tool_calls_by_tool == {"Bash": 3}
        assert result.tokens == TokenUsage(input_tokens=100, output_tokens=50)
        assert len(result.agents) == 1

        agent = result.agents[0]
        assert agent.agent_name == "agent-a"
        assert agent.turn_count == 1
        assert agent.total_duration_s == 2.5
        assert agent.tool_calls_by_tool == {"Bash": 3}
        assert agent.tokens == TokenUsage(input_tokens=100, output_tokens=50)
        assert agent.terminal_outcome == "success"

    def test_multiple_turns_accumulate_sums(self) -> None:
        records = [
            _record(
                turn_index=0,
                duration_s=1.0,
                tool_calls_by_tool={"Bash": 2},
                tokens=TokenUsage(input_tokens=100, output_tokens=40),
                outcome_kind="clarification_needed",
            ),
            _record(
                turn_index=1,
                duration_s=3.0,
                tool_calls_by_tool={"Bash": 1, "Read": 5},
                tokens=TokenUsage(input_tokens=200, output_tokens=60),
                outcome_kind="success",
            ),
        ]
        result = summarize_run(_ListStore(records))

        assert result.turn_count == 2
        assert result.total_duration_s == 4.0
        assert result.tool_calls_by_tool == {"Bash": 3, "Read": 5}
        assert result.tokens == TokenUsage(input_tokens=300, output_tokens=100)

        agent = result.agents[0]
        assert agent.turn_count == 2
        assert agent.total_duration_s == 4.0
        assert agent.tool_calls_by_tool == {"Bash": 3, "Read": 5}
        assert agent.tokens == TokenUsage(input_tokens=300, output_tokens=100)
        assert agent.terminal_outcome == "success"  # highest turn_index

    def test_terminal_outcome_from_highest_turn_index(self) -> None:
        records = [
            _record(turn_index=2, outcome_kind="success"),
            _record(turn_index=0, outcome_kind="failed"),
            _record(turn_index=1, outcome_kind="clarification_needed"),
        ]
        result = summarize_run(_ListStore(records))
        assert result.agents[0].terminal_outcome == "success"


class TestSummarizeRunMultipleAgents:
    def test_agents_sorted_by_name(self) -> None:
        records = [
            _record(agent_name="zebra"),
            _record(agent_name="alpha"),
            _record(agent_name="middle"),
        ]
        result = summarize_run(_ListStore(records))
        assert [a.agent_name for a in result.agents] == ["alpha", "middle", "zebra"]

    def test_cross_agent_totals_aggregated(self) -> None:
        records = [
            _record(
                agent_name="agent-a",
                duration_s=1.0,
                tool_calls_by_tool={"Bash": 2},
                tokens=TokenUsage(input_tokens=100),
            ),
            _record(
                agent_name="agent-b",
                duration_s=3.0,
                tool_calls_by_tool={"Bash": 1, "Read": 4},
                tokens=TokenUsage(input_tokens=200),
            ),
        ]
        result = summarize_run(_ListStore(records))

        assert result.turn_count == 2
        assert result.total_duration_s == 4.0
        assert result.tool_calls_by_tool == {"Bash": 3, "Read": 4}
        assert result.tokens == TokenUsage(input_tokens=300)


class TestTokenAggregation:
    def test_all_none_turns_produce_none_aggregate(self) -> None:
        records = [
            _record(turn_index=0, tokens=TokenUsage()),
            _record(turn_index=1, tokens=TokenUsage()),
        ]
        result = summarize_run(_ListStore(records))
        assert result.tokens == TokenUsage()
        assert result.agents[0].tokens == TokenUsage()

    def test_mixed_none_and_int_sums_non_none_values_only(self) -> None:
        records = [
            _record(turn_index=0, tokens=TokenUsage(input_tokens=None, output_tokens=50)),
            _record(turn_index=1, tokens=TokenUsage(input_tokens=100, output_tokens=None)),
        ]
        result = summarize_run(_ListStore(records))
        assert result.tokens.input_tokens == 100
        assert result.tokens.output_tokens == 50
        assert result.tokens.cache_read_tokens is None
        assert result.tokens.cache_write_tokens is None

    def test_all_four_token_fields_aggregated(self) -> None:
        records = [
            _record(
                turn_index=0,
                tokens=TokenUsage(
                    input_tokens=10,
                    output_tokens=20,
                    cache_read_tokens=30,
                    cache_write_tokens=40,
                ),
            ),
            _record(
                turn_index=1,
                tokens=TokenUsage(
                    input_tokens=1,
                    output_tokens=2,
                    cache_read_tokens=3,
                    cache_write_tokens=4,
                ),
            ),
        ]
        result = summarize_run(_ListStore(records))
        assert result.tokens == TokenUsage(
            input_tokens=11,
            output_tokens=22,
            cache_read_tokens=33,
            cache_write_tokens=44,
        )


_PYTHONPATH = str(Path(__file__).parents[3] / "src")


class TestCliMainValidRun:
    def test_valid_run_id_prints_summary_to_stdout(self, tmp_path: Path) -> None:
        run_id = "test-run-001"
        obs_path = tmp_path / run_id / "observability.jsonl"
        obs_path.parent.mkdir(parents=True)
        record = _record(
            agent_name="my-agent",
            turn_index=0,
            duration_s=5.0,
            tool_calls_by_tool={"Bash": 2},
            tokens=TokenUsage(input_tokens=500, output_tokens=200),
            outcome_kind="success",
        )
        obs_path.write_text(record.model_dump_json() + "\n", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_foundry.observability.summary",
                run_id,
                "--artifacts-dir",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": _PYTHONPATH},
        )

        assert result.returncode == 0
        assert "Run Summary" in result.stdout
        assert "Total turns" in result.stdout
        assert "Total duration" in result.stdout
        assert "5.0s" in result.stdout
        assert "Bash" in result.stdout
        assert "500" in result.stdout
        assert "200" in result.stdout
        assert "my-agent" in result.stdout
        assert "success" in result.stdout

    def test_stdout_contains_per_agent_breakdown(self, tmp_path: Path) -> None:
        run_id = "test-run-002"
        obs_path = tmp_path / run_id / "observability.jsonl"
        obs_path.parent.mkdir(parents=True)
        record = _record(
            agent_name="planner",
            turn_index=0,
            duration_s=3.0,
            tool_calls_by_tool={"Read": 4},
            tokens=TokenUsage(input_tokens=None, output_tokens=None),
            outcome_kind="success",
        )
        obs_path.write_text(record.model_dump_json() + "\n", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_foundry.observability.summary",
                run_id,
                "--artifacts-dir",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": _PYTHONPATH},
        )

        assert result.returncode == 0
        assert "Per-agent breakdown" in result.stdout
        assert "planner" in result.stdout
        assert "N/A" in result.stdout  # None token fields rendered as N/A


class TestCliMainMissingRun:
    def test_nonexistent_run_id_exits_with_code_1(self, tmp_path: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_foundry.observability.summary",
                "nonexistent-run",
                "--artifacts-dir",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": _PYTHONPATH},
        )

        assert result.returncode == 1
        assert result.stderr != ""
