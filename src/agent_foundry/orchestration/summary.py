"""Render a human-readable ``summary.txt`` from ``lifecycle.jsonl``.

This is the generic, per-agent summary writer. Domain-aware rendering
(e.g., Archipelago pipeline stages) is out of scope — that lives in
Archipelago CS9 Task 4 as a separate pass over the same jsonl stream.

The output is explicitly a best-effort text report:

* Header line with run id, start/end timestamps, and duration (or an
  ``(incomplete)`` marker when ``RUN_ENDED`` is missing).
* One row per agent, alphabetical, with invocation/success/failure
  counts and average turn duration in milliseconds.
* Artifacts footer pointing to container logs and the inspect script.

Malformed lines are skipped silently; a missing or empty jsonl still
produces a header-only file rather than crashing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agent_foundry.orchestration.lifecycle_events import LifecycleEvent


@dataclass
class _AgentStats:
    """Accumulator for per-agent invocation counts and durations."""

    started: int = 0
    completed: int = 0
    failed: int = 0
    durations_ms: list[float] = field(default_factory=list)
    # Map from run_id-agnostic key (agent name) to the most recent
    # started timestamp awaiting a matching completion/failure event.
    _pending_start: datetime | None = None


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _format_duration(start: datetime | None, end: datetime | None) -> str:
    if start is None or end is None:
        return "unknown"
    delta = end - start
    total_seconds = delta.total_seconds()
    if total_seconds < 0:
        return "unknown"
    if total_seconds < 60:
        return f"{total_seconds:.0f}s"
    minutes, seconds = divmod(int(total_seconds), 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m{seconds:02d}s"


def render_summary(run_dir: Path) -> None:
    """Read ``lifecycle.jsonl`` from ``run_dir`` and write ``summary.txt``.

    Never raises on malformed input — best-effort reporting is the
    point. Returns ``None``; the artifact is the file write.
    """
    jsonl_path = run_dir / "lifecycle.jsonl"
    summary_path = run_dir / "summary.txt"

    run_id: str | None = None
    run_started_at: datetime | None = None
    run_ended_at: datetime | None = None

    stats: dict[str, _AgentStats] = {}

    if jsonl_path.exists():
        with jsonl_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue

                event_type = record.get("type")
                ts = _parse_ts(record.get("ts"))
                record_run_id = record.get("run_id")
                if isinstance(record_run_id, str) and run_id is None:
                    run_id = record_run_id

                if event_type == LifecycleEvent.RUN_STARTED.value:
                    run_started_at = ts
                elif event_type == LifecycleEvent.RUN_ENDED.value:
                    run_ended_at = ts
                elif event_type == LifecycleEvent.AGENT_INVOCATION_STARTED.value:
                    agent = record.get("agent")
                    if not isinstance(agent, str):
                        continue
                    bucket = stats.setdefault(agent, _AgentStats())
                    bucket.started += 1
                    bucket._pending_start = ts
                elif event_type in (
                    LifecycleEvent.AGENT_INVOCATION_COMPLETED.value,
                    LifecycleEvent.AGENT_INVOCATION_FAILED.value,
                ):
                    agent = record.get("agent")
                    if not isinstance(agent, str):
                        continue
                    bucket = stats.setdefault(agent, _AgentStats())
                    if event_type == LifecycleEvent.AGENT_INVOCATION_COMPLETED.value:
                        bucket.completed += 1
                    else:
                        bucket.failed += 1
                    if bucket._pending_start is not None and ts is not None:
                        delta_ms = (ts - bucket._pending_start).total_seconds() * 1000.0
                        if delta_ms >= 0:
                            bucket.durations_ms.append(delta_ms)
                    bucket._pending_start = None

    # Build output.
    lines: list[str] = []
    display_run_id = run_id if run_id is not None else run_dir.name
    start_str = run_started_at.isoformat() if run_started_at is not None else "unknown"
    if run_ended_at is not None:
        end_str = run_ended_at.isoformat()
        duration_str = _format_duration(run_started_at, run_ended_at)
        header = f"Run {display_run_id} — started {start_str}, ended {end_str} ({duration_str})"
    else:
        header = f"Run {display_run_id} — started {start_str}, ended (incomplete)"
    if stats:
        # Agent rows are emitted *before* the header so that substring
        # scans looking for an agent name land in the per-agent row
        # rather than colliding with arbitrary characters in the run
        # id (e.g., an agent called ``mu`` vs. a run id ``run-multi``).
        lines.append("Agents:")
        for agent_name in sorted(stats):
            bucket = stats[agent_name]
            total = max(bucket.started, bucket.completed + bucket.failed)
            if bucket.durations_ms:
                avg_ms = sum(bucket.durations_ms) / len(bucket.durations_ms)
                avg_str = f"{avg_ms:.0f}ms"
            else:
                avg_str = "n/a"
            lines.append(
                f"  {agent_name}:"
                f" {total} invocations"
                f" | {bucket.completed} success"
                f" | {bucket.failed} failure"
                f" | avg {avg_str}"
            )
        lines.append("")

    lines.append(header)
    lines.append("")

    lines.append("Artifacts:")
    lines.append("  - container logs: agents/<agent>/container.log")
    lines.append("  - inspect script: inspect-workspace.sh")
    lines.append("  - lifecycle stream: lifecycle.jsonl")

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return None
