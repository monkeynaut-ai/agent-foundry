"""Eval suite for the ``design_review`` AICall.

Run with::

    ./lab/eval_tests/run_design_review_eval.sh
"""

from lab.eval_tests.ai_call.design_review import DesignInput, DesignReviewOutput, design_review
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import IsInstance

from agent_foundry.evals.models import AICallTarget, EvalSuite

_GOOD_DESIGN = """\
## Feature: Idempotent payment retry

When a charge fails with a transient error (network timeout, 5xx from
the gateway), retry up to 3 times with exponential backoff (1s, 2s,
4s). Each attempt uses the same idempotency key so the gateway dedupes
on its side. After 3 failures, surface the original error to the
caller and emit a `payment.retry_exhausted` event for the ops team.

Trade-offs: longer p99 latency on transient failures (worst case ~7s
of backoff) in exchange for reduced operator-visible flakiness. Errors
that are non-transient (e.g., card declined) are not retried — the
gateway error class drives the decision.
"""


_BAD_DESIGN = """\
## Feature: Auth

Add login. Users sign in. Store something somewhere. Return success
or failure.
"""


suite = EvalSuite(
    name="design_review",
    target=AICallTarget(ai_call=design_review),
    dataset=Dataset[DesignInput, DesignReviewOutput, None](
        name="design_review_v1",
        cases=[
            Case(
                name="good_design",
                inputs=DesignInput(document=_GOOD_DESIGN),
            ),
            Case(
                name="bad_design",
                inputs=DesignInput(document=_BAD_DESIGN),
            ),
        ],
        evaluators=[IsInstance(type_name="DesignReviewOutput")],
    ),
    invocations_per_case=1,
)
