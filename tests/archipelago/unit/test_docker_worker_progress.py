"""Docker worker progress parsing — checkpoint file and resume point tests."""

import json

from archipelago.docker_worker.models import ProgressEvent, TestRunRecord
from archipelago.docker_worker.progress import (
    get_resume_point,
    parse_progress,
    transform_progress_events,
)


def _event(type_: str, pr_id: str, commit_id: str, ts: float) -> dict:
    return {
        "type": type_,
        "pr_id": pr_id,
        "commit_id": commit_id,
        "status": "ok",
        "timestamp": ts,
    }


class TestParseProgress:
    def test_given_valid_jsonl_file_when_parsed_then_returns_progress_events(self, tmp_path):
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

    def test_given_invalid_json_line_when_parsed_then_skips_line_and_logs_warning(self, tmp_path):
        lines = [
            json.dumps(_event("commit_started", "pr1", "c1", 1.0)),
            "not valid json",
            json.dumps(_event("commit_green", "pr1", "c1", 3.0)),
        ]
        (tmp_path / "progress.jsonl").write_text("\n".join(lines))
        events = parse_progress(tmp_path)
        assert len(events) == 2

    def test_given_events_out_of_order_when_parsed_then_returns_sorted_by_timestamp(self, tmp_path):
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


class TestTransformProgressEvents:
    def test_given_empty_events_when_transformed_then_returns_empty_lists(self):
        patches, evidence = transform_progress_events([])
        assert patches == []
        assert evidence == []

    def test_given_pr_completed_event_when_transformed_then_patch_info_created(self):
        events = [
            ProgressEvent(
                **{
                    **_event("pr_completed", "pr1", "c1", 1.0),
                    "files_changed": ["src/foo.py", "tests/test_foo.py"],
                    "notes": "Added foo feature",
                }
            ),
        ]
        patches, evidence = transform_progress_events(events)
        assert len(patches) == 1
        assert patches[0].pr_id == "pr1"
        assert patches[0].branch_name == "c1"
        assert patches[0].files_changed == ["src/foo.py", "tests/test_foo.py"]
        assert patches[0].diff_summary == "Added foo feature"
        assert evidence == []

    def test_given_commit_green_event_when_transformed_then_commit_evidence_created(self):
        events = [
            ProgressEvent(
                **{
                    **_event("commit_green", "pr1", "c1", 1.0),
                    "tests_run": [
                        TestRunRecord(
                            command="pytest", exit_code=0, output_summary="3 passed"
                        ).model_dump(),
                    ],
                    "notes": "All tests pass",
                }
            ),
        ]
        patches, evidence = transform_progress_events(events)
        assert patches == []
        assert len(evidence) == 1
        assert evidence[0].commit_id == "c1"
        assert evidence[0].pr_id == "pr1"
        assert evidence[0].test_commands_run == ["pytest"]
        assert evidence[0].test_output == "All tests pass"
        assert evidence[0].tests_passed == 1
        assert evidence[0].tests_failed == 0
        assert evidence[0].all_green is True

    def test_given_mixed_events_when_transformed_then_only_relevant_types_extracted(self):
        events = [
            ProgressEvent(**_event("commit_started", "pr1", "c1", 1.0)),
            ProgressEvent(**_event("commit_green", "pr1", "c1", 2.0)),
            ProgressEvent(**_event("blocked", "pr1", "c2", 3.0)),
            ProgressEvent(
                **{
                    **_event("pr_completed", "pr1", "c1", 4.0),
                    "files_changed": ["a.py"],
                }
            ),
        ]
        patches, evidence = transform_progress_events(events)
        assert len(patches) == 1
        assert len(evidence) == 1

    def test_given_commit_green_with_mixed_results_when_transformed_then_counts_correct(self):
        events = [
            ProgressEvent(
                **{
                    **_event("commit_green", "pr1", "c1", 1.0),
                    "tests_run": [
                        TestRunRecord(
                            command="pytest tests/unit", exit_code=0, output_summary="5 passed"
                        ).model_dump(),
                        TestRunRecord(
                            command="pytest tests/integration",
                            exit_code=0,
                            output_summary="2 passed",
                        ).model_dump(),
                        TestRunRecord(
                            command="pytest tests/e2e", exit_code=1, output_summary="1 failed"
                        ).model_dump(),
                    ],
                    "notes": "Mixed results",
                }
            ),
        ]
        patches, evidence = transform_progress_events(events)
        assert len(evidence) == 1
        assert evidence[0].tests_passed == 2
        assert evidence[0].tests_failed == 1
        assert evidence[0].all_green is False
