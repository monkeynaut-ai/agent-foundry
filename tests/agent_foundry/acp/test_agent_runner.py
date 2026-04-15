"""Pin that the legacy import path re-exports the real executor.

Plan 1 shipped ``agent_foundry.acp.agent_runner.run_agent_in_container``
as a ``NotImplementedError`` stub. Phase F0 replaced it with the real
implementation from ``agent_foundry.orchestration.container_executor``.
Phase F.4 of Plan 2 is a no-op reconfirmation: this test asserts the
two symbols are the same object, so any future refactor that
accidentally re-introduces a stub will fail here.
"""

from __future__ import annotations


def test_run_agent_in_container_is_real_executor() -> None:
    from agent_foundry.acp.agent_runner import run_agent_in_container
    from agent_foundry.orchestration.container_executor import (
        run_agent_in_container as real_impl,
    )

    assert run_agent_in_container is real_impl
