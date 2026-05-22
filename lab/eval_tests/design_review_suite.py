"""Real-world smoke test for the AICall eval path.

AICall under test: a design-review classifier that takes a design
document and returns a structured review (summary, findings, approved
flag). Mirrors the declaration in ``lab/ai_call_tests/test_design_review.py``
but is self-contained so the eval CLI can load it without lab-path
gymnastics.

Run with::

    ./lab/eval_tests/run_design_review_eval.sh
"""

from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import IsInstance

from agent_foundry.ai_models.inference import InferenceParameters
from agent_foundry.ai_models.model import Model
from agent_foundry.evals.models import AICallTarget, EvalSuite
from agent_foundry.primitives.ai_call import AICall, ModelInput


class DesignInput(BaseModel):
    document: str


class ReviewFinding(BaseModel):
    area: str
    severity: str
    observation: str


class DesignReviewOutput(BaseModel):
    summary: str
    findings: list[ReviewFinding]
    approved: bool


_INSTRUCTIONS = """\
You are a senior software architect conducting a design review.

Evaluate the submitted design document against these criteria:
- Clarity: is the design clearly explained?
- Completeness: are key decisions and trade-offs covered?
- Risk: are there obvious gaps or risks?

Identify findings by area (e.g. "data model", "api surface", "error handling").
Severity values: "low", "medium", "high".
Set approved to true only if there are no high-severity findings.
"""


def _build_prompt(state: DesignInput) -> str:
    return f"Review the following design document:\n\n{state.document}"


design_review = AICall[DesignInput, DesignReviewOutput](
    model_input=ModelInput[DesignInput](
        instructions=_INSTRUCTIONS,
        prompt=_build_prompt,
    ),
    parameters=InferenceParameters(max_tokens=1024),
    model=Model.CLAUDE_HAIKU_4_5,
)


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
