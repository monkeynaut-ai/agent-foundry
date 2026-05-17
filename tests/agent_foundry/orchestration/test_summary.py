"""Tests for ``render_summary``.

Reads ``lifecycle.jsonl`` from a run directory and writes a generic,
per-agent ``summary.txt``. Domain-aware rendering happens downstream
in Archipelago and is explicitly out of scope here.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.summary import render_summary


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def _invocation_pair(
    *,
    run_id: str,
    agent: str,
    start_ts: str,
    end_ts: str,
    failed: bool = False,
) -> list[dict]:
    started = {
        "type": LifecycleEvent.AGENT_INVOCATION_STARTED.value,
        "ts": start_ts,
        "run_id": run_id,
        "agent": agent,
    }
    end_type = (
        LifecycleEvent.AGENT_INVOCATION_FAILED
        if failed
        else LifecycleEvent.AGENT_INVOCATION_COMPLETED
    )
    ended = {
        "type": end_type.value,
        "ts": end_ts,
        "run_id": run_id,
        "agent": agent,
    }
    return [started, ended]


def _run_started(run_id: str, ts: str) -> dict:
    return {
        "type": LifecycleEvent.RUN_STARTED.value,
        "ts": ts,
        "run_id": run_id,
    }


def _run_ended(run_id: str, ts: str) -> dict:
    return {
        "type": LifecycleEvent.RUN_ENDED.value,
        "ts": ts,
        "run_id": run_id,
    }


def test_render_summary_complete_run(tmp_path: Path) -> None:
    run_id = "run-complete"
    run_dir = tmp_path / run_id
    records: list[dict] = []
    records.append(_run_started(run_id, "2026-04-15T10:00:00+00:00"))
    # planner: 2 invocations, one success (500ms) and one success (1500ms)
    records.extend(
        _invocation_pair(
            run_id=run_id,
            agent="planner",
            start_ts="2026-04-15T10:00:01+00:00",
            end_ts="2026-04-15T10:00:01.500000+00:00",
        )
    )
    records.extend(
        _invocation_pair(
            run_id=run_id,
            agent="planner",
            start_ts="2026-04-15T10:00:02+00:00",
            end_ts="2026-04-15T10:00:03.500000+00:00",
        )
    )
    records.append(_run_ended(run_id, "2026-04-15T10:00:30+00:00"))
    _write_jsonl(run_dir / "lifecycle.jsonl", records)

    render_summary(run_dir)

    summary = (run_dir / "summary.txt").read_text(encoding="utf-8")
    assert run_id in summary
    assert "2026-04-15T10:00:00" in summary
    assert "2026-04-15T10:00:30" in summary
    # Duration 30s should surface somewhere in the header.
    assert "30" in summary
    # Per-agent row for planner.
    assert "planner" in summary
    # 2 invocations, 2 success, 0 failure.
    assert "2" in summary
    # Average of 500ms + 1500ms = 1000ms.
    assert "1000" in summary
    # Artifacts section.
    assert "Artifacts" in summary
    assert "incomplete" not in summary.lower()


def test_render_summary_partial_run_marks_incomplete(tmp_path: Path) -> None:
    run_id = "run-partial"
    run_dir = tmp_path / run_id
    records: list[dict] = [_run_started(run_id, "2026-04-15T09:00:00+00:00")]
    records.extend(
        _invocation_pair(
            run_id=run_id,
            agent="worker",
            start_ts="2026-04-15T09:00:01+00:00",
            end_ts="2026-04-15T09:00:02+00:00",
        )
    )
    # No RUN_ENDED event.
    _write_jsonl(run_dir / "lifecycle.jsonl", records)

    render_summary(run_dir)

    summary = (run_dir / "summary.txt").read_text(encoding="utf-8")
    assert "incomplete" in summary.lower()
    assert run_id in summary
    assert "worker" in summary


def test_render_summary_no_invocations_still_renders(tmp_path: Path) -> None:
    run_id = "run-empty"
    run_dir = tmp_path / run_id
    records = [
        _run_started(run_id, "2026-04-15T08:00:00+00:00"),
        _run_ended(run_id, "2026-04-15T08:00:05+00:00"),
    ]
    _write_jsonl(run_dir / "lifecycle.jsonl", records)

    render_summary(run_dir)

    summary_path = run_dir / "summary.txt"
    assert summary_path.exists()
    summary = summary_path.read_text(encoding="utf-8")
    # Header present with run id.
    assert run_id in summary
    # No crash — just no agent rows to render.


def test_render_summary_multiple_agents_alphabetical(tmp_path: Path) -> None:
    run_id = "run-multi"
    run_dir = tmp_path / run_id
    records: list[dict] = [_run_started(run_id, "2026-04-15T07:00:00+00:00")]

    # Insertion order: zeta, alpha, mu — but expected render order is alpha, mu, zeta.
    for agent, start, end, failed in [
        ("zeta", "2026-04-15T07:00:01+00:00", "2026-04-15T07:00:02+00:00", False),
        ("alpha", "2026-04-15T07:00:03+00:00", "2026-04-15T07:00:04+00:00", False),
        ("mu", "2026-04-15T07:00:05+00:00", "2026-04-15T07:00:06+00:00", True),
    ]:
        records.extend(
            _invocation_pair(
                run_id=run_id,
                agent=agent,
                start_ts=start,
                end_ts=end,
                failed=failed,
            )
        )
    records.append(_run_ended(run_id, "2026-04-15T07:00:30+00:00"))
    _write_jsonl(run_dir / "lifecycle.jsonl", records)

    render_summary(run_dir)

    summary = (run_dir / "summary.txt").read_text(encoding="utf-8")
    idx_alpha = summary.find("alpha")
    idx_mu = summary.find("mu")
    idx_zeta = summary.find("zeta")
    assert idx_alpha != -1 and idx_mu != -1 and idx_zeta != -1, summary
    assert idx_alpha < idx_mu < idx_zeta, (
        f"agents must appear alphabetically, got order alpha={idx_alpha} "
        f"mu={idx_mu} zeta={idx_zeta}"
    )


def test_render_summary_counts_success_and_failure_separately(tmp_path: Path) -> None:
    run_id = "run-mixed"
    run_dir = tmp_path / run_id
    records: list[dict] = [_run_started(run_id, "2026-04-15T06:00:00+00:00")]

    # 3 invocations for "builder": 2 success, 1 failure.
    records.extend(
        _invocation_pair(
            run_id=run_id,
            agent="builder",
            start_ts="2026-04-15T06:00:01+00:00",
            end_ts="2026-04-15T06:00:02+00:00",
        )
    )
    records.extend(
        _invocation_pair(
            run_id=run_id,
            agent="builder",
            start_ts="2026-04-15T06:00:03+00:00",
            end_ts="2026-04-15T06:00:04+00:00",
        )
    )
    records.extend(
        _invocation_pair(
            run_id=run_id,
            agent="builder",
            start_ts="2026-04-15T06:00:05+00:00",
            end_ts="2026-04-15T06:00:06+00:00",
            failed=True,
        )
    )
    records.append(_run_ended(run_id, "2026-04-15T06:00:10+00:00"))
    _write_jsonl(run_dir / "lifecycle.jsonl", records)

    render_summary(run_dir)

    summary = (run_dir / "summary.txt").read_text(encoding="utf-8")
    # Locate the builder row and check the numeric counts appear on it.
    builder_line = next(
        (line for line in summary.splitlines() if "builder" in line),
        None,
    )
    assert builder_line is not None, summary
    # 3 invocations total, 2 success, 1 failure.
    assert "3" in builder_line
    assert "2" in builder_line
    assert "1" in builder_line


def _run_failed(run_id: str, ts: str) -> dict:
    return {
        "type": LifecycleEvent.RUN_FAILED.value,
        "ts": ts,
        "run_id": run_id,
    }


def test_render_summary_treats_run_failed_as_terminal(tmp_path: Path) -> None:
    """RUN_FAILED is a terminal event; ``(incomplete)`` must not appear."""
    run_id = "run-failed"
    run_dir = tmp_path / run_id
    _write_jsonl(
        run_dir / "lifecycle.jsonl",
        [
            _run_started(run_id, "2026-04-15T08:00:00+00:00"),
            _run_failed(run_id, "2026-04-15T08:00:05+00:00"),
        ],
    )

    render_summary(run_dir)

    summary = (run_dir / "summary.txt").read_text(encoding="utf-8")
    assert "(incomplete)" not in summary
    assert "2026-04-15T08:00:05" in summary


def test_render_summary_marks_run_failed_in_header(tmp_path: Path) -> None:
    """The summary header surfaces a ``failed`` status for failed runs."""
    run_id = "run-failed-header"
    run_dir = tmp_path / run_id
    _write_jsonl(
        run_dir / "lifecycle.jsonl",
        [
            _run_started(run_id, "2026-04-15T08:00:00+00:00"),
            _run_failed(run_id, "2026-04-15T08:00:05+00:00"),
        ],
    )

    render_summary(run_dir)

    summary = (run_dir / "summary.txt").read_text(encoding="utf-8")
    header = next((line for line in summary.splitlines() if "failed" in line), None)
    assert header is not None, f"Expected a 'failed' status in header; got:\n{summary}"


def test_render_summary_returns_none(tmp_path: Path) -> None:
    run_id = "run-return"
    run_dir = tmp_path / run_id
    _write_jsonl(
        run_dir / "lifecycle.jsonl",
        [
            _run_started(run_id, "2026-04-15T05:00:00+00:00"),
            _run_ended(run_id, "2026-04-15T05:00:01+00:00"),
        ],
    )

    result = render_summary(run_dir)

    assert result is None


def test_render_summary_includes_failure_cause(tmp_path: Path) -> None:
    run_id = "run-fail"
    run_dir = tmp_path / run_id
    _write_jsonl(
        run_dir / "lifecycle.jsonl",
        [
            _run_started(run_id, "2026-04-15T10:00:00+00:00"),
            {
                "type": LifecycleEvent.AGENT_INVOCATION_FAILED.value,
                "ts": "2026-04-15T10:01:00+00:00",
                "run_id": run_id,
                "agent_name": "implementer",
                "invocation": 1,
                "exit_code": 1,
                "oom_killed": False,
                "api_error_status": 500,
                "num_turns": 2,
                "reason": "claude exec failed (exit=1): ...",
            },
            _run_failed(run_id, "2026-04-15T10:01:01+00:00"),
        ],
    )

    render_summary(run_dir)

    text = (run_dir / "summary.txt").read_text()
    assert "Failures:" in text
    assert "implementer/1" in text
    assert "api_error_status=500" in text
    assert "exit_code=1" in text
