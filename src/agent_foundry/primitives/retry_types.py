"""Types for Retry exhaustion reporting.

``RetryExhaustion`` is currently unused — the on_exhaustion hook it described was
removed; nothing wires it into the Retry path.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# Fixed, resolver-knowable field names for the exhaustion-metadata channels the
# compiler writes into a Retry's scope before its resolver node. A resolver
# input model declares these exact names to read the corresponding value; they
# are not prefix-namespaced because a resolver author cannot know the Retry's
# compile prefix.
WELL_KNOWN_METADATA_FIELDS: frozenset[str] = frozenset({"exhaustion_reason", "attempt_failures"})


class AttemptOutcome(StrEnum):
    """Whether a single attempt passed the Retry primitive's until() condition.

    A raise is mapped to NOT_PASSED by exception_policy; there is no errored member.
    """

    PASSED = "passed"
    NOT_PASSED = "not_passed"


class RetryExhaustionReason(StrEnum):
    """Why a Retry primitive exhausted all attempts without until() returning True.

    - CONDITION_NOT_MET: all attempts ran to completion; until() never returned True.
    - BODY_EXCEPTIONS: every attempt raised under the CATCH_AND_CONTINUE policy;
      no attempt completed normally.
    - MIXED: at least one attempt raised (and was tolerated under CATCH_AND_CONTINUE)
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
    """Exhaustion report describing a Retry that consumed all attempts.

    Currently unused: no longer wired to a hook after on_exhaustion was removed.

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


class DispositionKind(StrEnum):
    ACCEPT = "accept"
    ABORT = "abort"
    RETRY = "retry"


class ResolverDisposition(BaseModel):
    """Routing signal a resolver primitive emits when the automated phase exhausts.

    Pure routing — carries no state. The state the compiler continues/accepts/re-runs
    with is the resolver node's own merged output state, already in graph state. The
    compiler reads ``kind`` to route; ``reason`` is the operator's ABORT explanation
    (ignored for ACCEPT/RETRY).
    """

    kind: DispositionKind
    reason: str = ""


class RetryAborted(Exception):
    """Raised when a resolver returns ABORT. Carries the abort reason.

    Terminates the run via the raise path (clean-signal variant deferred).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ResolverDidNotConvergeError(Exception):
    """Raised when consecutive RETRY re-entries hit the safety backstop ceiling.

    A safety invariant trip, not an intentional abort.
    """

    def __init__(self, ceiling: int) -> None:
        self.ceiling = ceiling
        super().__init__(f"resolver did not converge after {ceiling} consecutive retries")
