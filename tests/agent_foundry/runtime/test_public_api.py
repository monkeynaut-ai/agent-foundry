"""Public-API export guarantees for runtime accessors."""

import agent_foundry.runtime as runtime


def test_runtime_accessors_are_publicly_exported():
    from agent_foundry.runtime import artifacts_dir, cancelled, emit, responder, run_id

    expected = {
        "artifacts_dir",
        "cancelled",
        "emit",
        "responder",
        "run_id",
    }

    assert expected <= set(runtime.__all__)
    assert runtime.artifacts_dir is artifacts_dir
    assert runtime.cancelled is cancelled
    assert runtime.emit is emit
    assert runtime.responder is responder
    assert runtime.run_id is run_id
