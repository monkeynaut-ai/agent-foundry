"""``EvalSuite`` — the in-memory declaration of a single evaluation run."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent_foundry.evals.models.cases import Dataset
from agent_foundry.evals.models.targets import EvalTarget


class EvalSuite(BaseModel):
    """Single-target eval suite declaration."""

    name: str = Field(min_length=1)
    target: EvalTarget
    dataset: Dataset
    invocations_per_case: int = Field(ge=1)
