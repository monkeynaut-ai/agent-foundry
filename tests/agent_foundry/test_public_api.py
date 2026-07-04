"""Top-level public API guarantees."""

import agent_foundry


def test_top_level_exports_common_framework_surface():
    from agent_foundry import (
        AgentAction,
        AICall,
        AsyncFunctionAction,
        Conditional,
        ContainerReusePolicy,
        FunctionAction,
        GateAction,
        Loop,
        ModelInput,
        Process,
        Retry,
        RunCompleted,
        Sequence,
        StdinResponder,
        run_process,
        static_provider,
    )

    expected = {
        "AICall",
        "AgentAction",
        "AsyncFunctionAction",
        "Conditional",
        "ContainerReusePolicy",
        "FunctionAction",
        "GateAction",
        "Loop",
        "ModelInput",
        "Process",
        "Retry",
        "RunCompleted",
        "Sequence",
        "StdinResponder",
        "run_process",
        "static_provider",
    }

    assert expected <= set(agent_foundry.__all__)
    assert AICall is agent_foundry.AICall
    assert AgentAction is agent_foundry.AgentAction
    assert AsyncFunctionAction is agent_foundry.AsyncFunctionAction
    assert Conditional is agent_foundry.Conditional
    assert ContainerReusePolicy is agent_foundry.ContainerReusePolicy
    assert FunctionAction is agent_foundry.FunctionAction
    assert GateAction is agent_foundry.GateAction
    assert Loop is agent_foundry.Loop
    assert ModelInput is agent_foundry.ModelInput
    assert Process is agent_foundry.Process
    assert Retry is agent_foundry.Retry
    assert RunCompleted is agent_foundry.RunCompleted
    assert Sequence is agent_foundry.Sequence
    assert StdinResponder is agent_foundry.StdinResponder
    assert callable(run_process)
    assert callable(static_provider)
