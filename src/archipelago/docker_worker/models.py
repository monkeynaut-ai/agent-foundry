"""Data models for the Docker worker subsystem."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class WorkerConstraints(BaseModel):
    """Resource and policy constraints for a Docker worker run."""

    timeout_seconds: int = 3600
    max_cost_usd: float | None = None
    allowed_commands: list[str] = Field(default_factory=list)
    network_policy: str = "none"
    mem_limit_mb: int = 512
    cpu_quota: int | None = None
    pids_limit: int | None = None


class WorkerInput(BaseModel):
    """Typed input for the coding.implement_feature_from_spec capability."""

    repo_ref: str
    feature_spec: dict[str, Any]
    constraints: WorkerConstraints
    test_commands: list[str]
    gates: list[str] = Field(default_factory=list)


class PatchInfo(BaseModel):
    """Metadata about a patch/PR produced by the worker."""

    pr_id: str
    branch_name: str
    files_changed: list[str]
    diff_summary: str


class CommitEvidence(BaseModel):
    """Evidence collected for a single commit."""

    commit_id: str
    pr_id: str
    test_commands_run: list[str]
    test_output: str
    tests_passed: int
    tests_failed: int
    all_green: bool


class WorkerResult(BaseModel):
    """Typed output from the coding.implement_feature_from_spec capability."""

    result_summary: str
    workspace_ref: str
    patches: list[PatchInfo]
    evidence: list[CommitEvidence]
    status: Literal["completed", "failed", "interrupted", "timed_out"]


class TestRunRecord(BaseModel):
    """Record of a single test command execution."""

    __test__ = False

    command: str
    exit_code: int
    output_summary: str


class ProgressEvent(BaseModel):
    """A structured progress checkpoint emitted by CC to progress.jsonl."""

    type: Literal["commit_started", "commit_green", "pr_completed", "blocked"]
    pr_id: str
    commit_id: str
    files_changed: list[str] = Field(default_factory=list)
    tests_added: list[str] = Field(default_factory=list)
    tests_run: list[TestRunRecord] = Field(default_factory=list)
    status: str
    notes: str = ""
    timestamp: float


class ClarificationRequest(BaseModel):
    """Parsed payload from ARCHIPELAGO_NEED_CLARIFICATION marker."""

    question: str
    options: list[str] = Field(default_factory=list)
    default: str | None = None
    blocking: bool = True


class PermissionRequest(BaseModel):
    """Parsed payload from ARCHIPELAGO_NEED_PERMISSION marker."""

    action: str
    risk_level: Literal["low", "medium", "high"]
    why_needed: str
    alternatives: list[str] = Field(default_factory=list)


class UpdateAvailable(BaseModel):
    """Parsed payload from ARCHIPELAGO_UPDATE_AVAILABLE marker."""

    installed: str
    latest: str


class ResumePoint(BaseModel):
    """Identifies where to resume work after a crash or pause."""

    pr_id: str
    commit_id: str
    status: str
