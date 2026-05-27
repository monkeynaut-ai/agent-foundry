import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_foundry.observability.models import AgentTurnRecord, StopReason, TokenUsage
from agent_foundry.observability.store import JsonlObservabilityStore, NoOpObservabilityStore


def _make_record(turn_index: int = 0) -> AgentTurnRecord:
    return AgentTurnRecord(
        agent_name="test-agent",
        turn_index=turn_index,
        started_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        ended_at=datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC),
        duration_s=5.0,
        tool_calls_by_tool={"Read": 1},
        tokens=TokenUsage(input_tokens=100, output_tokens=50),
        subagent_spawns=0,
        stop_reason=StopReason.END_TURN,
        outcome_kind="success",
        resume_retries=0,
        model="claude-sonnet-4-6",
    )


class TestJsonlObservabilityStore:
    def test_append_writes_valid_json_line(self, tmp_path: Path) -> None:
        path = tmp_path / "obs.jsonl"
        store = JsonlObservabilityStore(path)
        store.append(_make_record())
        store.close()
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["agent_name"] == "test-agent"
        assert data["turn_index"] == 0

    def test_flush_per_record_visible_before_close(self, tmp_path: Path) -> None:
        path = tmp_path / "obs.jsonl"
        store = JsonlObservabilityStore(path)
        store.append(_make_record())
        content = path.read_text(encoding="utf-8")
        assert content.strip() != ""
        store.close()

    def test_iter_records_deserialises_in_insertion_order(self, tmp_path: Path) -> None:
        path = tmp_path / "obs.jsonl"
        records = [_make_record(i) for i in range(3)]
        store = JsonlObservabilityStore(path)
        for r in records:
            store.append(r)
        store.close()
        # iter_records opens the file fresh — works even after close
        restored = list(store.iter_records())
        assert len(restored) == 3
        for original, read_back in zip(records, restored, strict=True):
            assert original == read_back

    def test_iter_records_on_empty_file_returns_empty_iterator(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.touch()
        store = JsonlObservabilityStore(path)
        store.close()
        assert list(store.iter_records()) == []

    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        path = tmp_path / "obs.jsonl"
        store = JsonlObservabilityStore(path)
        store.close()
        store.close()  # second call must not raise

    def test_context_manager_closes_file_after_with_block(self, tmp_path: Path) -> None:
        path = tmp_path / "obs.jsonl"
        with JsonlObservabilityStore(path) as store:
            store.append(_make_record())
        assert store._closed is True

    def test_context_manager_closes_on_exception(self, tmp_path: Path) -> None:
        path = tmp_path / "obs.jsonl"
        store = JsonlObservabilityStore(path)
        try:
            with store:
                raise ValueError("intentional error")
        except ValueError:
            pass
        assert store._closed is True

    def test_append_raises_runtime_error_when_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "obs.jsonl"
        store = JsonlObservabilityStore(path)
        store.close()
        with pytest.raises(RuntimeError, match="closed"):
            store.append(_make_record())

    def test_creates_parent_directories_automatically(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "dir" / "obs.jsonl"
        with JsonlObservabilityStore(path) as store:
            store.append(_make_record())
        assert path.exists()


class TestNoOpObservabilityStore:
    def test_append_silently_accepts_record(self) -> None:
        store = NoOpObservabilityStore()
        store.append(_make_record())  # must not raise

    def test_iter_records_returns_empty_iterator(self) -> None:
        store = NoOpObservabilityStore()
        assert list(store.iter_records()) == []

    def test_close_is_no_op(self) -> None:
        store = NoOpObservabilityStore()
        store.close()
        store.close()  # idempotent — must not raise
