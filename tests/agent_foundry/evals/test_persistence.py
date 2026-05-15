"""Tests for ``agent_foundry.evals.persistence``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EqualsExpected

from agent_foundry.evals.models import RunResult
from agent_foundry.evals.persistence import read_report_json, write_report


class _Input(BaseModel):
    text: str


class _Output(BaseModel):
    result: str


async def _passing_task(inp: _Input) -> _Output:
    return _Output(result=inp.text.upper())


async def _make_run_result(*, run_id: str = "r1", invocations: int = 1) -> RunResult:
    dataset = Dataset[_Input, _Output, None](
        name="ds",
        cases=[
            Case(name="c1", inputs=_Input(text="a"), expected_output=_Output(result="A")),
            Case(name="c2", inputs=_Input(text="b"), expected_output=_Output(result="B")),
        ],
        evaluators=[EqualsExpected()],
    )
    report = await dataset.evaluate(_passing_task, repeat=invocations, progress=False)
    return RunResult(
        run_id=run_id,
        suite_name="s",
        started_at=datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC),
        ended_at=datetime(2026, 5, 15, 12, 0, 1, tzinfo=UTC),
        invocations_per_case=invocations,
        report=report,
    )


@pytest.mark.asyncio
async def test_write_report_creates_run_directory(tmp_path: Path) -> None:
    """write_report creates <out_dir>/<run_id>/report.json."""
    result = await _make_run_result(run_id="20260515T120000_abcd1234")
    path = write_report(result, tmp_path)
    assert path == tmp_path / "20260515T120000_abcd1234" / "report.json"
    assert path.is_file()


@pytest.mark.asyncio
async def test_write_report_creates_missing_parent_dirs(tmp_path: Path) -> None:
    """write_report creates intermediate directories if absent."""
    result = await _make_run_result()
    nested = tmp_path / "deeply" / "nested" / "evals_runs"
    path = write_report(result, nested)
    assert path.is_file()


@pytest.mark.asyncio
async def test_write_report_includes_metadata(tmp_path: Path) -> None:
    """The written JSON includes all RunResult top-level fields."""
    result = await _make_run_result(run_id="r2", invocations=2)
    path = write_report(result, tmp_path)
    data = json.loads(path.read_text())
    assert data["run_id"] == "r2"
    assert data["suite_name"] == "s"
    assert data["invocations_per_case"] == 2
    assert "started_at" in data
    assert "ended_at" in data
    assert "report" in data


@pytest.mark.asyncio
async def test_write_report_serializes_full_report(tmp_path: Path) -> None:
    """The persisted report contains per-(case, invocation) entries."""
    result = await _make_run_result(invocations=3)
    path = write_report(result, tmp_path)
    data = json.loads(path.read_text())
    # 2 cases x 3 repeats = 6 entries.
    assert len(data["report"]["cases"]) == 6
    names = {c["name"] for c in data["report"]["cases"]}
    assert "c1 [1/3]" in names
    assert "c2 [3/3]" in names


@pytest.mark.asyncio
async def test_read_report_json_round_trips_dict(tmp_path: Path) -> None:
    """write_report then read_report_json yields an equal dict."""
    result = await _make_run_result()
    path = write_report(result, tmp_path)
    loaded = read_report_json(path)
    re_serialized = json.loads(path.read_text())
    assert loaded == re_serialized


@pytest.mark.asyncio
async def test_read_report_json_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_report_json(tmp_path / "does_not_exist.json")
