"""Terminal-outcome envelope returned by ``run_primitive_plan``.

Every run ends by returning exactly one ``RunOutcome`` variant:

* ``RunCompleted`` — the validated product output.
* ``RunAborted`` — a deliberate operator ABORT (not an error).
* ``RunFailed`` — a safety backstop trip or an unexpected crash,
  distinguished by ``error_kind``.

Callers branch on ``RunOutcome.kind`` rather than catching exceptions.
This is an orchestration concept (it is what the runner returns), kept
separate from the primitives layer.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

__all__ = [
    "FailureKind",
    "RunAborted",
    "RunCompleted",
    "RunFailed",
    "RunOutcome",
    "RunOutcomeKind",
]


class RunOutcomeKind(StrEnum):
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"


class FailureKind(StrEnum):
    """Why a run ended in ``RunFailed``.

    - BACKSTOP: the resolver-convergence safety ceiling tripped.
    - CRASH: any other escaped exception.
    """

    BACKSTOP = "backstop"
    CRASH = "crash"


class RunCompleted(BaseModel):
    """The run produced and validated the product output."""

    kind: Literal[RunOutcomeKind.COMPLETED] = RunOutcomeKind.COMPLETED
    output: BaseModel


class RunAborted(BaseModel):
    """A resolver returned ABORT; the run stopped deliberately, not in error.

    ``reason`` is the operator's ABORT explanation.
    """

    kind: Literal[RunOutcomeKind.ABORTED] = RunOutcomeKind.ABORTED
    reason: str = ""


class RunFailed(BaseModel):
    """The run ended on a safety backstop trip or an unexpected crash.

    Carries string-reconstructable fields rather than the live exception
    so the envelope round-trips as JSON; the traceback-bearing object is
    delivered separately to ``on_run_ended`` hooks.
    """

    kind: Literal[RunOutcomeKind.FAILED] = RunOutcomeKind.FAILED
    error_kind: FailureKind
    error_type: str
    message: str


RunOutcome = Annotated[
    RunCompleted | RunAborted | RunFailed,
    Field(discriminator="kind"),
]
