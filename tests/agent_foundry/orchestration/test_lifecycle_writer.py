"""Tests for LifecycleWriter.

An append-only JSONL writer with auto-stamped ``ts`` / ``run_id`` fields,
thread-safe and durable under mid-write crash.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

import pytest

from agent_foundry.orchestration.lifecycle_writer import LifecycleWriter


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_append_writes_jsonl_line_with_autostamps(tmp_path: Path) -> None:
    writer = LifecycleWriter(run_id="run-abc", path=tmp_path / "lifecycle.jsonl")
    try:
        writer.append({"type": "test", "foo": 1})
    finally:
        writer.close()

    lines = _read_lines(tmp_path / "lifecycle.jsonl")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["run_id"] == "run-abc"
    assert record["type"] == "test"
    assert record["foo"] == 1
    # ts is ISO 8601 parseable.
    parsed = datetime.fromisoformat(record["ts"])
    assert parsed.tzinfo is not None


def test_append_empty_event_still_has_ts_and_run_id(tmp_path: Path) -> None:
    path = tmp_path / "lifecycle.jsonl"
    writer = LifecycleWriter(run_id="run-empty", path=path)
    try:
        writer.append({})
    finally:
        writer.close()

    [line] = _read_lines(path)
    record = json.loads(line)
    assert set(record.keys()) == {"ts", "run_id"}
    assert record["run_id"] == "run-empty"


def test_append_run_event_is_public_alias(tmp_path: Path) -> None:
    path = tmp_path / "lifecycle.jsonl"
    writer = LifecycleWriter(run_id="run-alias", path=path)
    try:
        writer.append_run_event({"type": "domain", "n": 7})
    finally:
        writer.close()

    [line] = _read_lines(path)
    record = json.loads(line)
    assert record["type"] == "domain"
    assert record["n"] == 7
    assert record["run_id"] == "run-alias"


def test_append_is_flushed_and_readable_from_another_handle(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lifecycle.jsonl"
    writer = LifecycleWriter(run_id="run-flush", path=path)
    try:
        writer.append({"type": "early"})
        # Separate handle — must see the line immediately (flushed per append).
        with path.open("r", encoding="utf-8") as reader:
            content = reader.read()
        assert content.count("\n") == 1
        record = json.loads(content.strip())
        assert record["type"] == "early"
    finally:
        writer.close()


def test_concurrent_appends_produce_no_interleaving(tmp_path: Path) -> None:
    path = tmp_path / "lifecycle.jsonl"
    writer = LifecycleWriter(run_id="run-threads", path=path)

    N = 20
    barrier = threading.Barrier(N)

    def worker(idx: int) -> None:
        barrier.wait()
        writer.append({"type": "thread-event", "idx": idx})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        writer.close()

    lines = _read_lines(path)
    assert len(lines) == N
    seen_indices: set[int] = set()
    for line in lines:
        record = json.loads(line)  # Must parse — no interleaving.
        assert record["run_id"] == "run-threads"
        assert record["type"] == "thread-event"
        seen_indices.add(record["idx"])
    assert seen_indices == set(range(N))


def test_partial_log_survives_mid_write_truncation(tmp_path: Path) -> None:
    path = tmp_path / "lifecycle.jsonl"
    writer = LifecycleWriter(run_id="run-crash", path=path)
    try:
        writer.append({"type": "first", "n": 1})
        writer.append({"type": "second", "n": 2})
        writer.append({"type": "third", "n": 3})
    finally:
        writer.close()

    raw = path.read_bytes()
    # Simulate a mid-write crash: truncate somewhere inside the last record
    # (after the first two complete lines finish).
    first_two = b"\n".join(raw.split(b"\n")[:2]) + b"\n"
    assert first_two in raw
    # Append a partial third line (half of the third record's bytes) to
    # simulate the crash scenario.
    third_bytes = raw.split(b"\n")[2]
    partial = first_two + third_bytes[: max(1, len(third_bytes) // 2)]
    path.write_bytes(partial)

    lines = path.read_text(encoding="utf-8").splitlines()
    # Line-based recovery: first two records still parse cleanly.
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["type"] == "first"
    assert second["type"] == "second"
    # The last (truncated) line should not be a valid JSON record.
    if len(lines) >= 3:
        with pytest.raises(json.JSONDecodeError):
            json.loads(lines[2])


def test_append_after_close_raises(tmp_path: Path) -> None:
    path = tmp_path / "lifecycle.jsonl"
    writer = LifecycleWriter(run_id="run-closed", path=path)
    writer.append({"type": "ok"})
    writer.close()
    with pytest.raises(RuntimeError, match="closed"):
        writer.append({"type": "nope"})


def test_close_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "lifecycle.jsonl"
    writer = LifecycleWriter(run_id="run-idem", path=path)
    writer.close()
    # Second close must not raise.
    writer.close()


def test_parent_directory_is_created(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c" / "lifecycle.jsonl"
    writer = LifecycleWriter(run_id="run-mkdir", path=nested)
    try:
        writer.append({"type": "made-it"})
    finally:
        writer.close()
    assert nested.exists()
    [line] = _read_lines(nested)
    assert json.loads(line)["type"] == "made-it"
