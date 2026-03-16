"""Docker worker data models — validation and round-trip tests."""

import time

import pytest
from pydantic import ValidationError

from archipelago.docker_worker.models import (
    ClarificationRequest,
    CommitEvidence,
    PatchInfo,
    PermissionRequest,
    ProgressEvent,
    ResumePoint,
    WorkerConstraints,
    WorkerInput,
    WorkerResult,
)


def _valid_worker_constraints() -> dict:
    return {
        "timeout_seconds": 1800,
        "max_cost_usd": 5.0,
        "allowed_commands": ["pytest", "git"],
        "network_policy": "restricted",
    }


def _valid_worker_input() -> dict:
    return {
        "repo_ref": "abc123",
        "repo_url": "https://github.com/org/repo",
        "feature_spec": {"title": "Test Feature", "objective": "Test"},
        "constraints": _valid_worker_constraints(),
        "test_commands": ["pdm run pytest"],
        "gates": ["spec_approval"],
    }


def _valid_patch_info() -> dict:
    return {
        "pr_id": "pr-1",
        "branch_name": "feat/test",
        "files_changed": ["src/foo.py"],
        "diff_summary": "Added foo module",
    }


def _valid_commit_evidence() -> dict:
    return {
        "commit_id": "def456",
        "pr_id": "pr-1",
        "test_commands_run": ["pdm run pytest"],
        "test_output": "5 passed",
        "tests_passed": 5,
        "tests_failed": 0,
        "all_green": True,
    }


def _valid_worker_result() -> dict:
    return {
        "result_summary": "Feature implemented successfully",
        "workspace_ref": "workspace-abc",
        "patches": [_valid_patch_info()],
        "evidence": [_valid_commit_evidence()],
        "status": "completed",
    }


def _valid_progress_event() -> dict:
    return {
        "type": "commit_started",
        "pr_id": "pr-1",
        "commit_id": "abc123",
        "files_changed": ["src/foo.py"],
        "tests_added": ["test_foo.py"],
        "tests_run": [{"command": "pytest", "exit_code": 0, "output_summary": "ok"}],
        "status": "in_progress",
        "notes": "Starting commit",
        "timestamp": time.time(),
    }


# ── Commit 1: WorkerInput, WorkerConstraints, WorkerResult, PatchInfo, CommitEvidence ──


class TestWorkerInput:
    def test_given_valid_fields_when_instantiated_then_validates(self):
        inp = WorkerInput(**_valid_worker_input())
        assert inp.repo_ref == "abc123"
        assert len(inp.test_commands) == 1
        assert len(inp.gates) == 1

    def test_given_valid_instance_when_json_round_tripped_then_no_field_loss(self):
        inp = WorkerInput(**_valid_worker_input())
        reconstructed = WorkerInput.model_validate_json(inp.model_dump_json())
        assert reconstructed == inp

    def test_given_missing_required_field_when_instantiated_then_raises_validation_error(
        self,
    ):
        data = _valid_worker_input()
        del data["repo_ref"]
        with pytest.raises(ValidationError) as exc_info:
            WorkerInput(**data)
        field_names = [e["loc"][0] for e in exc_info.value.errors()]
        assert "repo_ref" in field_names

    def test_given_valid_fields_with_repo_url_when_instantiated_then_repo_url_accessible(self):
        inp = WorkerInput(**_valid_worker_input())
        assert inp.repo_url == "https://github.com/org/repo"

    def test_given_no_repo_url_when_instantiated_then_repo_url_defaults_to_none(self):
        data = _valid_worker_input()
        del data["repo_url"]
        inp = WorkerInput(**data)
        assert inp.repo_url is None

    def test_given_role_config_when_instantiated_then_fields_accessible(self):
        data = _valid_worker_input()
        data["worker_mode"] = "unit_test_writer"
        data["acp_hidden_dirs"] = ["/workspace/src"]
        data["acp_readonly_dirs"] = []
        data["role_instructions_path"] = "/home/claude/.claude/CLAUDE-unit-test-writer.md"
        data["workspace_volume"] = "archipelago-123"
        inp = WorkerInput(**data)
        assert inp.worker_mode == "unit_test_writer"
        assert inp.acp_hidden_dirs == ["/workspace/src"]
        assert inp.role_instructions_path == "/home/claude/.claude/CLAUDE-unit-test-writer.md"
        assert inp.workspace_volume == "archipelago-123"

    def test_given_no_role_config_when_instantiated_then_defaults_empty(self):
        inp = WorkerInput(**_valid_worker_input())
        assert inp.worker_mode == "full"
        assert inp.acp_hidden_dirs == []
        assert inp.acp_readonly_dirs == []
        assert inp.role_instructions_path is None
        assert inp.workspace_volume is None


class TestWorkerConstraints:
    def test_given_no_args_when_instantiated_then_defaults_applied(self):
        constraints = WorkerConstraints()
        assert constraints.timeout_seconds == 3600
        assert constraints.max_cost_usd is None
        assert constraints.allowed_commands == []
        assert constraints.network_policy == "none"

    def test_given_no_args_when_instantiated_then_turn_timeout_seconds_defaults_to_3600(self):
        assert WorkerConstraints().turn_timeout_seconds == 3600

    def test_given_no_args_when_instantiated_then_skip_permissions_defaults_to_false(self):
        assert WorkerConstraints().skip_permissions is False

    def test_given_turn_timeout_and_skip_permissions_when_json_round_tripped_then_values_preserved(
        self,
    ):
        c = WorkerConstraints(turn_timeout_seconds=7200, skip_permissions=True)
        reconstructed = WorkerConstraints.model_validate_json(c.model_dump_json())
        assert reconstructed.turn_timeout_seconds == 7200
        assert reconstructed.skip_permissions is True


class TestWorkerResult:
    def test_given_valid_fields_when_instantiated_then_validates(self):
        result = WorkerResult(**_valid_worker_result())
        assert result.status == "completed"
        assert len(result.patches) == 1
        assert len(result.evidence) == 1

    def test_given_valid_instance_when_json_round_tripped_then_no_field_loss(self):
        result = WorkerResult(**_valid_worker_result())
        reconstructed = WorkerResult.model_validate_json(result.model_dump_json())
        assert reconstructed == result


@pytest.mark.parametrize(
    "model_cls,data_factory",
    [
        (PatchInfo, _valid_patch_info),
        (CommitEvidence, _valid_commit_evidence),
    ],
    ids=["PatchInfo", "CommitEvidence"],
)
class TestSimpleModelValidation:
    def test_given_valid_fields_when_instantiated_then_validates(self, model_cls, data_factory):
        instance = model_cls(**data_factory())
        assert instance is not None


# ── Commit 2: ProgressEvent, TestRunRecord, interrupt models, ResumePoint ──


class TestProgressEvent:
    def test_given_valid_commit_started_when_instantiated_then_validates(self):
        event = ProgressEvent(**_valid_progress_event())
        assert event.type == "commit_started"
        assert event.pr_id == "pr-1"

    def test_given_valid_instance_when_json_round_tripped_then_no_field_loss(self):
        event = ProgressEvent(**_valid_progress_event())
        reconstructed = ProgressEvent.model_validate_json(event.model_dump_json())
        assert reconstructed == event

    def test_given_invalid_type_when_instantiated_then_raises_validation_error(self):
        data = _valid_progress_event()
        data["type"] = "invalid_type"
        with pytest.raises(ValidationError):
            ProgressEvent(**data)


class TestClarificationRequest:
    def test_given_valid_fields_when_instantiated_then_validates(self):
        req = ClarificationRequest(question="Which DB?", options=["pg", "mysql"], default="pg")
        assert req.question == "Which DB?"
        assert len(req.options) == 2

    def test_given_defaults_when_instantiated_then_blocking_is_true(self):
        req = ClarificationRequest(question="Which DB?")
        assert req.blocking is True
        assert req.options == []
        assert req.default is None


class TestPermissionRequest:
    def test_given_valid_fields_when_instantiated_then_validates(self):
        req = PermissionRequest(
            action="install lodash",
            risk_level="low",
            why_needed="Data transforms",
            alternatives=["implement manually"],
        )
        assert req.risk_level == "low"

    def test_given_invalid_risk_level_when_instantiated_then_raises_validation_error(
        self,
    ):
        with pytest.raises(ValidationError):
            PermissionRequest(action="delete prod", risk_level="extreme", why_needed="test")


class TestResumePoint:
    def test_given_valid_fields_when_instantiated_then_validates(self):
        rp = ResumePoint(pr_id="pr-1", commit_id="abc", status="blocked")
        assert rp.pr_id == "pr-1"
        assert rp.status == "blocked"
