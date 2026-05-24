"""Agent-foundry-owned ``Case`` and ``Dataset`` types.

These mirror the conceptual shape of Pydantic-Evals' equivalents
(``Case``, ``Dataset``) but are pure agent-foundry Pydantic models —
no ``pydantic_evals`` import. Translation to and from the execution
backend's representation lives in :mod:`agent_foundry.evals.runners`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_foundry.evals.models.evaluators import EvaluatorSpec


class Case(BaseModel):
    """A single evaluation input + optional expected output + metadata."""

    name: str = Field(min_length=1)
    inputs: BaseModel
    expected_output: BaseModel | None = None
    metadata: BaseModel | dict[str, Any] | None = None


class Dataset(BaseModel):
    """A named collection of cases plus the evaluators applied to each.

    The runner is responsible for executing the dataset's cases against
    a task callable and applying ``evaluators`` to each output.
    """

    name: str = Field(min_length=1)
    cases: list[Case]
    evaluators: list[EvaluatorSpec] = Field(default_factory=list)
