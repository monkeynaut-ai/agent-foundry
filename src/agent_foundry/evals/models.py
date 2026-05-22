"""Core data models for the eval harness.

``EvalSuite`` is the in-memory declaration of a single evaluation run —
the target under test, the dataset, and the configuration. ``RunResult``
is the artifact produced by executing the suite — metadata plus the
per-invocation :class:`pydantic_evals.reporting.EvaluationReport`
objects.

A suite's target is one of:

- :class:`AgentTarget` — wraps an :class:`AgentAction` for evaluation
  through the full container-backed orchestration path.
- :class:`AICallTarget` — wraps an :class:`AICall` for evaluation
  through :func:`invoke_ai_call`, no container or orchestration.

The two share the runner and reporting machinery; only task
construction differs.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals import Dataset
from pydantic_evals.reporting import EvaluationReport

from agent_foundry.primitives.ai_call import AICall
from agent_foundry.primitives.models import AgentAction


class EvalTargetKind(StrEnum):
    """Discriminator value for eval target variants."""

    AGENT = "agent"
    AI_CALL = "ai_call"


class AgentTarget(BaseModel):
    """Eval target backed by a multi-turn containerized agent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: Literal[EvalTargetKind.AGENT] = EvalTargetKind.AGENT
    agent: AgentAction


class AICallTarget(BaseModel):
    """Eval target backed by a single ``AICall`` declaration."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: Literal[EvalTargetKind.AI_CALL] = EvalTargetKind.AI_CALL
    ai_call: AICall


type EvalTarget = Annotated[AgentTarget | AICallTarget, Field(discriminator="kind")]


class EvalSuite(BaseModel):
    """Single-target eval suite declaration."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = Field(min_length=1)
    target: EvalTarget
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
