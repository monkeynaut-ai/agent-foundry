"""Docker worker progress parsing — checkpoint file and resume point tests."""

import json
import time

import pytest

from archipelago.docker_worker.models import ProgressEvent, ResumePoint
from archipelago.docker_worker.progress import get_resume_point, parse_progress


def _event(type_: str, pr_id: str, commit_id: str, ts: float) -> dict:
    return {
        "type": type_,
        "pr_id": pr_id,
        "commit_id": commit_id,
        "status": "ok",
        "timestamp": ts,
    }


class TestParseProgress:
    def test_given_valid_jsonl_file_when_parsed_then_returns_progress_events(
        self, tmp_path
    ):
        lines = [
            json.dumps(_event("commit_started", "pr1", "c1", 1.0)),
            json.dumps(_event("commit_green", "pr1", "c1", 2.0)),
        ]
        (tmp_path / "progress.jsonl").write_text("\n".join(lines))
        events = parse_progress(tmp_path)
        assert len(events) == 2
        assert all(isinstance(e, ProgressEvent) for e in events)

    def test_given_empty_file_when_parsed_then_returns_empty_list(self, tmp_path):
        (tmp_path / "progress.jsonl").write_text("")
        events = parse_progress(tmp_path)
        assert events == []

    def test_given_invalid_json_line_when_parsed_then_skips_line_and_logs_warning(
        self, tmp_path
    ):
        lines = [
            json.dumps(_event("commit_started", "pr1", "c1", 1.0)),
            "not valid json",
            json.dumps(_event("commit_green", "pr1", "c1", 3.0)),
        ]
        (tmp_path / "progress.jsonl").write_text("\n".join(lines))
        events = parse_progress(tmp_path)
        assert len(events) == 2

    def test_given_events_out_of_order_when_parsed_then_returns_sorted_by_timestamp(
        self, tmp_path
    ):
        lines = [
            json.dumps(_event("commit_green", "pr1", "c1", 5.0)),
            json.dumps(_event("commit_started", "pr1", "c1", 1.0)),
        ]
        (tmp_path / "progress.jsonl").write_text("\n".join(lines))
        events = parse_progress(tmp_path)
        assert events[0].timestamp < events[1].timestamp


class TestGetResumePoint:
    def test_given_all_commits_green_when_calculated_then_returns_none(self):
        events = [
            ProgressEvent(**_event("commit_started", "pr1", "c1", 1.0)),
            ProgressEvent(**_event("commit_green", "pr1", "c1", 2.0)),
        ]
        assert get_resume_point(events) is None

    def test_given_blocked_at_commit_when_calculated_then_returns_that_commit(self):
        events = [
            ProgressEvent(**_event("commit_started", "pr1", "c1", 1.0)),
            ProgressEvent(**_event("commit_green", "pr1", "c1", 2.0)),
            ProgressEvent(**_event("commit_started", "pr1", "c2", 3.0)),
            ProgressEvent(**_event("blocked", "pr1", "c2", 4.0)),
        ]
        rp = get_resume_point(events)
        assert rp is not None
        assert rp.pr_id == "pr1"
        assert rp.commit_id == "c2"
        assert rp.status == "blocked"

    def test_given_commit_started_but_no_green_when_calculated_then_returns_that_commit(
        self,
    ):
        events = [
            ProgressEvent(**_event("commit_started", "pr1", "c1", 1.0)),
        ]
        rp = get_resume_point(events)
        assert rp is not None
        assert rp.commit_id == "c1"
        assert rp.status == "commit_started"

    def test_given_pr_completed_and_next_pr_started_when_calculated_then_returns_next_pr_commit(
        self,
    ):
        events = [
            ProgressEvent(**_event("commit_started", "pr1", "c1", 1.0)),
            ProgressEvent(**_event("commit_green", "pr1", "c1", 2.0)),
            ProgressEvent(**_event("pr_completed", "pr1", "c1", 3.0)),
            ProgressEvent(**_event("commit_started", "pr2", "c1", 4.0)),
        ]
        rp = get_resume_point(events)
        assert rp is not None
        assert rp.pr_id == "pr2"
        assert rp.commit_id == "c1"
