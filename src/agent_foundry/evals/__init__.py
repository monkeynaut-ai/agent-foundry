"""Public eval surface for Agent Foundry.

The eval package exposes declarative eval models, target registries, and task
builders without requiring callers to import runner internals.
"""

from agent_foundry.evals.agent_foundry_tasks import (
    EvalResponderInvokedError,
    EvalRunNotCompletedError,
    RaiseOnInvokeResponder,
    build_invoke_ai_call_task,
    build_run_process_task,
)
from agent_foundry.evals.models import (
    AgentTarget,
    AICallTarget,
    AssertionResult,
    Case,
    CaseFailure,
    CaseResult,
    Dataset,
    EqualsExpectedSpec,
    EvalSuite,
    EvalTarget,
    EvalTargetKind,
    EvaluationReport,
    EvaluatorKind,
    EvaluatorSpec,
    IsInstanceSpec,
    LLMJudgeSpec,
    Runner,
    RunResult,
    Task,
)
from agent_foundry.evals.registry import (
    AICallRegistry,
    DuplicateAICallError,
    UnknownAICallError,
)

__all__ = [
    "AICallRegistry",
    "AICallTarget",
    "AgentTarget",
    "AssertionResult",
    "Case",
    "CaseFailure",
    "CaseResult",
    "Dataset",
    "DuplicateAICallError",
    "EqualsExpectedSpec",
    "EvalResponderInvokedError",
    "EvalRunNotCompletedError",
    "EvalSuite",
    "EvalTarget",
    "EvalTargetKind",
    "EvaluationReport",
    "EvaluatorKind",
    "EvaluatorSpec",
    "IsInstanceSpec",
    "LLMJudgeSpec",
    "RaiseOnInvokeResponder",
    "RunResult",
    "Runner",
    "Task",
    "UnknownAICallError",
    "build_invoke_ai_call_task",
    "build_run_process_task",
]
