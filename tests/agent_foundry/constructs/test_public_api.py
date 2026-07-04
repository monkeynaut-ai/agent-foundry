"""Public-API export guarantees.

Products discover constructs and the run entry point through the package's
public surface; these tests pin that surface so a future refactor can't
silently drop a symbol.
"""

import agent_foundry.constructs as constructs
import agent_foundry.orchestration as orchestration


def test_aicall_is_publicly_exported():
    from agent_foundry.constructs import AICall, ModelInput

    assert "AICall" in constructs.__all__
    assert "ModelInput" in constructs.__all__
    assert constructs.AICall is AICall
    assert constructs.ModelInput is ModelInput


def test_construct_extension_helpers_are_publicly_exported():
    from agent_foundry.constructs import Construct, get_type_args

    assert {"Construct", "get_type_args"} <= set(constructs.__all__)
    assert constructs.Construct is Construct
    assert constructs.get_type_args is get_type_args


def test_run_process_is_publicly_exported():
    from agent_foundry.orchestration import run_process

    assert "run_process" in orchestration.__all__
    assert callable(run_process)


def test_run_outcome_types_are_publicly_exported():
    # Products inspect the run outcome after run_process; the outcome types
    # must be importable from the public package, not an internal module.
    from agent_foundry.orchestration import RunAborted, RunCompleted, RunFailed, RunOutcome

    for name in ("RunCompleted", "RunAborted", "RunFailed", "RunOutcome"):
        assert name in orchestration.__all__
    assert RunCompleted is not None
    assert RunAborted is not None
    assert RunFailed is not None
    assert RunOutcome is not None
