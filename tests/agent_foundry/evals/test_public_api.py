"""Public-API export guarantees for evals."""

import agent_foundry.evals as evals


def test_evals_models_and_registry_are_publicly_exported():
    from agent_foundry.evals import (
        AgentTarget,
        AICallRegistry,
        AICallTarget,
        Case,
        Dataset,
        EvalSuite,
        EvalTarget,
        EvaluationReport,
        RunResult,
        build_invoke_ai_call_task,
        build_run_process_task,
    )

    expected = {
        "AICallRegistry",
        "AICallTarget",
        "AgentTarget",
        "Case",
        "Dataset",
        "EvalSuite",
        "EvalTarget",
        "EvaluationReport",
        "RunResult",
        "build_invoke_ai_call_task",
        "build_run_process_task",
    }

    assert expected <= set(evals.__all__)
    assert AICallRegistry is evals.AICallRegistry
    assert AICallTarget is evals.AICallTarget
    assert AgentTarget is evals.AgentTarget
    assert Case is evals.Case
    assert Dataset is evals.Dataset
    assert EvalSuite is evals.EvalSuite
    assert EvalTarget is evals.EvalTarget
    assert EvaluationReport is evals.EvaluationReport
    assert RunResult is evals.RunResult
    assert callable(build_invoke_ai_call_task)
    assert callable(build_run_process_task)
