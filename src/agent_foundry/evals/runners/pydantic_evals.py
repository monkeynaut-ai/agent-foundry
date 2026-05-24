"""``PydanticEvalsRunner`` — execution backend using ``pydantic_evals``.

This is the **only** file in agent-foundry that imports
``pydantic_evals``. An ``import-linter`` contract enforces the
boundary. The runner translates agent-foundry's declarative types into
pydantic-evals' equivalents at call time, executes the dataset, and
translates the resulting report back into agent-foundry types before
returning.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from pydantic_evals import Case as PECase
from pydantic_evals import Dataset as PEDataset
from pydantic_evals.evaluators import EqualsExpected as PEEqualsExpected
from pydantic_evals.evaluators import IsInstance as PEIsInstance
from pydantic_evals.evaluators import LLMJudge as PELLMJudge

from agent_foundry.evals.models import (
    AssertionResult,
    CaseFailure,
    CaseResult,
    Dataset,
    EvalSuite,
    EvaluationReport,
    EvaluatorKind,
    EvaluatorSpec,
    Runner,
    RunResult,
    Task,
)


class PydanticEvalsRunner(Runner):
    """Runner that delegates execution to the ``pydantic_evals`` library."""

    async def run(
        self,
        suite: EvalSuite,
        *,
        task: Task,
        max_concurrency: int = 1,
    ) -> RunResult:
        """Execute ``suite`` and return a typed agent-foundry :class:`RunResult`."""
        started_at = datetime.now(UTC)
        run_id = _generate_run_id(started_at)

        pe_dataset = _to_pe_dataset(suite.dataset)
        pe_report = await pe_dataset.evaluate(
            task,
            repeat=suite.invocations_per_case,
            max_concurrency=max_concurrency,
            progress=False,
        )

        ended_at = datetime.now(UTC)

        return RunResult(
            run_id=run_id,
            suite_name=suite.name,
            started_at=started_at,
            ended_at=ended_at,
            invocations_per_case=suite.invocations_per_case,
            report=_from_pe_report(pe_report, name=suite.dataset.name),
        )


# ---------------------------------------------------------------------------
# Translation: agent-foundry types -> pydantic-evals types
# ---------------------------------------------------------------------------


def _to_pe_evaluator(spec: EvaluatorSpec) -> Any:
    if spec.kind is EvaluatorKind.EQUALS_EXPECTED:
        return PEEqualsExpected()
    if spec.kind is EvaluatorKind.IS_INSTANCE:
        return PEIsInstance(type_name=spec.type_name)
    if spec.kind is EvaluatorKind.LLM_JUDGE:
        kwargs: dict[str, Any] = {"rubric": spec.rubric}
        if spec.model is not None:
            kwargs["model"] = spec.model
        return PELLMJudge(**kwargs)
    raise ValueError(f"Unknown evaluator kind: {spec.kind!r}")


def _to_pe_dataset(dataset: Dataset) -> PEDataset:
    pe_cases = [
        PECase(
            name=c.name,
            inputs=c.inputs,
            expected_output=c.expected_output,
            metadata=c.metadata,
        )
        for c in dataset.cases
    ]
    pe_evaluators = [_to_pe_evaluator(e) for e in dataset.evaluators]
    return PEDataset(
        name=dataset.name,
        cases=pe_cases,
        evaluators=pe_evaluators,
    )


# ---------------------------------------------------------------------------
# Translation: pydantic-evals report -> agent-foundry report
# ---------------------------------------------------------------------------


def _from_pe_report(pe_report: Any, *, name: str) -> EvaluationReport:
    cases = [_from_pe_case(c) for c in pe_report.cases]
    failures = [_from_pe_failure(f) for f in getattr(pe_report, "failures", [])]
    return EvaluationReport(name=name, cases=cases, failures=failures)


def _from_pe_case(pe_case: Any) -> CaseResult:
    assertions = [
        AssertionResult(
            name=assertion_name,
            value=bool(result.value),
            reason=result.reason,
        )
        for assertion_name, result in (pe_case.assertions or {}).items()
    ]
    return CaseResult(
        name=pe_case.name,
        inputs=_dump(pe_case.inputs),
        output=_dump(pe_case.output),
        assertions=assertions,
    )


def _from_pe_failure(pe_failure: Any) -> CaseFailure:
    return CaseFailure(
        name=pe_failure.name,
        inputs=_dump(pe_failure.inputs),
        error=pe_failure.error_message,
    )


def _dump(value: Any) -> dict[str, Any]:
    """Coerce a model-or-dict value to a JSON-serializable dict."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return {"value": value}


def _generate_run_id(started_at: datetime) -> str:
    stamp = started_at.strftime("%Y%m%dT%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"{stamp}_{suffix}"
