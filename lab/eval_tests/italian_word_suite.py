"""Real-world smoke test for the eval harness.

Agent under test: a small classifier that decides whether a given word
is part of standard, modern Italian. Answers ``"yes"``, ``"no"``, or
``"uncertain"``.

Run with::

    pdm eval lab/eval_tests/italian_word_suite.py \\
        --artifacts-dir <path-for-lifecycle-events> \\
        --workspace-volume <docker-volume-name> \\
        --base-image-tag agent-worker:latest

Fill in the case ``inputs.word`` and ``expected_output.answer`` values
before running — they are TODO placeholders.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EqualsExpected

from agent_foundry.evals.models import AgentTarget, EvalSuite
from agent_foundry.orchestration.container_executor import run_agent_in_container
from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy

# ---------------------------------------------------------------------------
# Typed boundary models
# ---------------------------------------------------------------------------


class ItalianWordInput(BaseModel):
    """Input to the Italian-word classifier."""

    word: str = Field(description="A single word (or short phrase) to classify.")


class ItalianWordAnswer(BaseModel):
    """Output from the Italian-word classifier."""

    answer: str = Field(
        description=(
            'One of exactly three values: "yes", "no", or "uncertain". '
            "Lowercase, no punctuation, no other text."
        )
    )


# ---------------------------------------------------------------------------
# Agent declaration
# ---------------------------------------------------------------------------


_INSTRUCTIONS = """\
You are a linguistic classifier. Your task: decide whether a given word
is part of standard, modern Italian.

OUTPUT FORMAT
-------------
Return a structured response with a single field, `answer`, whose value
is exactly one of these three strings (lowercase, no punctuation):

  - "yes"
  - "no"
  - "uncertain"

Do not include reasoning, explanation, or any other text — only the
typed answer field.

CLASSIFICATION RULES
--------------------
Use these definitions strictly.

Answer "yes" when the word is part of standard, modern Italian. This
includes:
  * Native Italian vocabulary (e.g., "amore", "ciao", "tavolo").
  * Italian-origin words that travelled abroad but remain Italian
    (e.g., "pizza", "spaghetti", "opera").
  * Foreign loanwords now fully assimilated into modern Italian usage
    (e.g., "computer", "weekend", "sport").
  * Cognates that exist as Italian words even if shared with other
    Romance languages (e.g., "casa", "luna", "mano" — these are
    Italian words, regardless of also existing in Spanish/Portuguese).
  * Proper nouns of unambiguously Italian origin (e.g., "Roma",
    "Firenze", "Toscana").

Answer "no" when the word does not exist in standard, modern Italian.
This includes:
  * Latin words not carried into modern Italian (e.g., "veni",
    "vidi", "vici", "ergo").
  * Words from unrelated languages with no Italian form (e.g.,
    "hello", "ohayou", "ostavte").
  * Nonsense strings, typos, or fabricated tokens.

Answer "uncertain" when classification is genuinely ambiguous. This
includes:
  * Words from Italian regional dialects (Neapolitan, Sicilian,
    Venetian, etc.) that are not standard Italian.
  * Archaic Italian no longer in current use.
  * Spellings that could plausibly be Italian or another Romance
    language without context.
  * Proper nouns of unclear or contested origin.

DECISION DISCIPLINE
-------------------
1. Origin does not matter on its own — what matters is whether the
   word is part of modern Italian usage.
2. Treat the input case-insensitively when classifying.
3. Prefer "uncertain" over guessing when the case is genuinely
   ambiguous. Do not invent confidence you don't have.
4. Never answer anything other than "yes", "no", or "uncertain".
"""


def _build_prompt(inp: ItalianWordInput) -> str:
    return (
        f'Word: "{inp.word}"\n\n'
        "Is this word part of standard, modern Italian? "
        'Respond with the answer field set to "yes", "no", or "uncertain".'
    )


def _build_instructions(_: ItalianWordInput) -> str:
    return _INSTRUCTIONS


italian_word_agent = AgentAction[ItalianWordInput, ItalianWordAnswer](
    name="italian_word_classifier",
    prompt_builder=_build_prompt,
    instructions_provider=_build_instructions,
    # run_agent_in_container is typed against the generic BaseModel return; the
    # primitive constrains the actual return type at runtime via output_type.
    executor=run_agent_in_container,  # type: ignore[arg-type]
    reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    model="claude-haiku-4-5-20251001",
    effort="low",
)


# ---------------------------------------------------------------------------
# Eval suite — 5 placeholder cases (fill in word + answer before running)
# ---------------------------------------------------------------------------


suite = EvalSuite(
    name="italian_word_classifier",
    target=AgentTarget(agent=italian_word_agent),
    dataset=Dataset[ItalianWordInput, ItalianWordAnswer, None](
        name="italian_word_classifier_v1",
        cases=[
            Case(
                name="case_1",
                inputs=ItalianWordInput(word="molto"),
                expected_output=ItalianWordAnswer(answer="yes"),
            ),
            Case(
                name="case_2",
                inputs=ItalianWordInput(word="no"),
                expected_output=ItalianWordAnswer(answer="uncertain"),
            ),
            Case(
                name="case_3",
                inputs=ItalianWordInput(word="ciao"),
                expected_output=ItalianWordAnswer(answer="yes"),
            ),
            Case(
                name="case_4",
                inputs=ItalianWordInput(word="hello"),
                expected_output=ItalianWordAnswer(answer="no"),
            ),
            Case(
                name="case_5",
                inputs=ItalianWordInput(word="wasser"),
                expected_output=ItalianWordAnswer(answer="no"),
            ),
        ],
        evaluators=[EqualsExpected()],
    ),
    invocations_per_case=1,
)
