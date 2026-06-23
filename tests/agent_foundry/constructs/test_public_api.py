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


def test_run_process_is_publicly_exported():
    from agent_foundry.orchestration import run_process

    assert "run_process" in orchestration.__all__
    assert callable(run_process)
