"""Agent Foundry eval model layer.

Pure Pydantic declarative types — no third-party eval library imports.
Re-exports are flat so existing consumers can keep importing from
``agent_foundry.evals.models`` directly.
"""

from agent_foundry.evals.models.cases import Case, Dataset
from agent_foundry.evals.models.evaluators import (
    EqualsExpectedSpec,
    EvaluatorKind,
    EvaluatorSpec,
    IsInstanceSpec,
    LLMJudgeSpec,
)
from agent_foundry.evals.models.report import (
    AssertionResult,
    CaseFailure,
    CaseResult,
    EvaluationReport,
    RunResult,
)
from agent_foundry.evals.models.runner import Runner, Task
from agent_foundry.evals.models.suite import EvalSuite
from agent_foundry.evals.models.targets import (
    AgentTarget,
    AICallTarget,
    EvalTarget,
    EvalTargetKind,
)

__all__ = [
    "AICallTarget",
    "AgentTarget",
    "AssertionResult",
    "Case",
    "CaseFailure",
    "CaseResult",
    "Dataset",
    "EqualsExpectedSpec",
    "EvalSuite",
    "EvalTarget",
    "EvalTargetKind",
    "EvaluationReport",
    "EvaluatorKind",
    "EvaluatorSpec",
    "IsInstanceSpec",
    "LLMJudgeSpec",
    "RunResult",
    "Runner",
    "Task",
]
