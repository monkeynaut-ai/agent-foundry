"""Core data models for the eval harness.

``EvalSuite`` is the in-memory declaration of a single-agent evaluation
run — agent, dataset, and configuration. ``RunResult`` is the artifact
produced by executing the suite — metadata plus the per-invocation
:class:`pydantic_evals.reporting.EvaluationReport` objects.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals import Dataset
from pydantic_evals.reporting import EvaluationReport

from agent_foundry.primitives.models import AgentAction


class EvalSuite(BaseModel):
    """Single-agent eval suite declaration."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = Field(min_length=1)
    agent: AgentAction
    dataset: Dataset
    invocations_per_case: int = Field(ge=1)


class RunResult(BaseModel):
    """Result of executing an :class:`EvalSuite`.

    ``report`` is the single :class:`EvaluationReport` produced by
    Pydantic Evals' ``Dataset.evaluate(task, repeat=N)``. The report
    contains one entry per ``(case, invocation)`` pair, with names
    suffixed ``[i/N]``; per-case aggregation is recovered via
    :meth:`EvaluationReport.case_groups`.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str = Field(min_length=1)
    suite_name: str = Field(min_length=1)
    started_at: datetime
    ended_at: datetime
    invocations_per_case: int = Field(ge=1)
    report: EvaluationReport
