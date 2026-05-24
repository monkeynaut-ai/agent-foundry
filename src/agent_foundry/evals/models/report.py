"""Agent-foundry-owned evaluation report types.

The runner produces an :class:`EvaluationReport` per ``run_suite``
invocation, containing one :class:`CaseResult` per
``(case, invocation)`` pair. Failed cases (raised an exception during
the task call) are captured separately as :class:`CaseFailure`
entries.

These types are the runner's stable output contract — persistence,
the CLI renderer, and any future report viewer consume them directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AssertionResult(BaseModel):
    """One evaluator's verdict on one case."""

    name: str = Field(min_length=1)
    value: bool
    reason: str | None = None


class CaseResult(BaseModel):
    """A successful case invocation — the task ran and produced output."""

    name: str = Field(min_length=1)
    inputs: dict[str, Any]
    output: dict[str, Any]
    assertions: list[AssertionResult] = Field(default_factory=list)


class CaseFailure(BaseModel):
    """A case where the task raised an exception."""

    name: str = Field(min_length=1)
    inputs: dict[str, Any]
    error: str = Field(min_length=1)


class EvaluationReport(BaseModel):
    """Full report for one suite execution."""

    name: str = Field(min_length=1)
    cases: list[CaseResult] = Field(default_factory=list)
    failures: list[CaseFailure] = Field(default_factory=list)


class RunResult(BaseModel):
    """Top-level artifact of a suite execution."""

    run_id: str = Field(min_length=1)
    suite_name: str = Field(min_length=1)
    started_at: datetime
    ended_at: datetime
    invocations_per_case: int = Field(ge=1)
    report: EvaluationReport
