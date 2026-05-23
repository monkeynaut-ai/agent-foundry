"""Design-review AICall declaration.

A small structured-output classifier that takes a design document and
returns a summary, a list of findings (each with area / severity /
observation), and an ``approved`` flag.

Kept in the same folder as ``design_review_suite.py`` so the eval CLI
can load both via ``importlib`` without lab-path gymnastics.
"""

from pydantic import BaseModel

from agent_foundry.ai_models.inference import InferenceParameters
from agent_foundry.ai_models.model import Model
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
