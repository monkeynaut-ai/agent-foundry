"""Evaluator specifications — declarative configuration of how cases are scored.

Each evaluator spec is a small Pydantic model that names what kind of
evaluation should happen for each case. Specs are discriminated by
``kind`` so they serialize and validate cleanly. The runner translates
each spec into its backend-specific evaluator at execution time.

New evaluator kinds extend the union and add a translator entry in the
runner backend.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class EvaluatorKind(StrEnum):
    """Discriminator for evaluator spec variants."""

    EQUALS_EXPECTED = "equals_expected"
    IS_INSTANCE = "is_instance"
    LLM_JUDGE = "llm_judge"


class EqualsExpectedSpec(BaseModel):
    """Pass if the case's output equals the case's ``expected_output``."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[EvaluatorKind.EQUALS_EXPECTED] = EvaluatorKind.EQUALS_EXPECTED


class IsInstanceSpec(BaseModel):
    """Pass if the case's output is an instance of the named type.

    ``type_name`` is matched by class name, not by import path —
    matching mirrors the backend's behavior.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal[EvaluatorKind.IS_INSTANCE] = EvaluatorKind.IS_INSTANCE
    type_name: str = Field(min_length=1)


class LLMJudgeSpec(BaseModel):
    """Pass if an LLM judging the case output against ``rubric`` returns true."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[EvaluatorKind.LLM_JUDGE] = EvaluatorKind.LLM_JUDGE
    rubric: str = Field(min_length=1)
    model: str | None = None


type EvaluatorSpec = Annotated[
    EqualsExpectedSpec | IsInstanceSpec | LLMJudgeSpec,
    Field(discriminator="kind"),
]
