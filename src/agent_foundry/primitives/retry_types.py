"""Types for Retry exhaustion reporting passed to the on_exhaustion hook."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RetryExhaustionReason(StrEnum):
    """Why a Retry primitive exhausted all attempts without until() returning True.

    - CONDITION_NOT_MET: all attempts ran to completion; until() never returned True.
    - BODY_EXCEPTIONS: every attempt raised under the TREAT_AS_FAILURE policy;
      no attempt completed normally.
    - MIXED: at least one attempt raised (and was tolerated under TREAT_AS_FAILURE)
      and at least one attempt completed normally with until() returning False.
    """

    CONDITION_NOT_MET = "condition_not_met"
    BODY_EXCEPTIONS = "body_exceptions"
    MIXED = "mixed"


class AttemptFailure(BaseModel):
    attempt_num: int
    exception_type: str
    exception_message: str
    timestamp: datetime


class RetryExhaustion[I: BaseModel](BaseModel):
    """Passed to Retry.on_exhaustion when all attempts are consumed.

    ``last_state`` is the accumulated state at the moment of exhaustion —
    specifically, the state after all rollbacks complete. Under
    ``BODY_EXCEPTIONS`` where every attempt raised, this equals the pre-Retry
    input state (no body output was ever committed). Under ``CONDITION_NOT_MET``
    or ``MIXED``, it reflects the output of the last completed body attempt.
    Handlers must not assume ``last_state`` always reflects a body's output.
    """

    max_attempts: int
    reason: RetryExhaustionReason
    attempt_failures: list[AttemptFailure] = Field(default_factory=list)
    last_state: I
