"""Lab: AIRequest primitive — design review harness.

Exercises AIRequest with Anthropic as the provider. Declares a design_review
primitive that takes a design document as input and returns a structured
review result.

Since the AIRequest compiler is not yet implemented, this harness calls the
provider adapter directly. Once the compiler is wired up, this will be
replaced by run_primitive_plan.

Run:
    python lab/ai_request_tests/test_design_review.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

from agent_foundry.primitives.ai_request import (
    AIRequest,
    InferenceProvider,
    ModelConfiguration,
    ModelInput,
)
from agent_foundry.providers.anthropic_provider import call_anthropic

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")


# ---------------------------------------------------------------------------
# State models
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Inline runner — resolves AIRequest fields and delegates to provider adapter
# ---------------------------------------------------------------------------


async def run_ai_request(primitive: AIRequest, state: BaseModel) -> BaseModel:
    instructions = (
        primitive.model_input.instructions(state)
        if callable(primitive.model_input.instructions)
        else primitive.model_input.instructions
    )
    prompt = (
        primitive.model_input.prompt(state)
        if callable(primitive.model_input.prompt)
        else primitive.model_input.prompt
    )
    config = (
        primitive.model_configuration(state)
        if callable(primitive.model_configuration)
        else primitive.model_configuration
    )

    _, output_type = _get_type_args(primitive)

    if primitive.provider == InferenceProvider.ANTHROPIC:
        return await call_anthropic(instructions, prompt, config, output_type)

    raise NotImplementedError(f"provider not implemented in harness: {primitive.provider}")


def _get_type_args(primitive: AIRequest) -> tuple[type[BaseModel], type[BaseModel]]:
    metadata = type(primitive).__pydantic_generic_metadata__
    args = metadata["args"]
    if not args:
        raise TypeError("AIRequest must be parameterized")
    return args[0], args[1]


# ---------------------------------------------------------------------------
# Primitive declaration
# ---------------------------------------------------------------------------

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


def _prompt(state: DesignInput) -> str:
    return f"Review the following design document:\n\n{state.document}"


design_review = AIRequest[DesignInput, DesignReviewOutput](
    model_input=ModelInput[DesignInput](
        instructions=_INSTRUCTIONS,
        prompt=_prompt,
    ),
    model_configuration=ModelConfiguration(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
    ),
    provider=InferenceProvider.ANTHROPIC,
)

# ---------------------------------------------------------------------------
# Sample input
# ---------------------------------------------------------------------------

_SAMPLE_DESIGN = """\
## Feature: User Authentication

We will add JWT-based authentication. Users POST to /login with email and
password. On success, the server returns a signed JWT valid for 24 hours.
Subsequent requests include the token in the Authorization header.

No refresh token mechanism is planned. Tokens are stored client-side in
localStorage.
"""

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = asyncio.run(run_ai_request(design_review, DesignInput(document=_SAMPLE_DESIGN)))
    print(result.model_dump_json(indent=2))
