"""Pin that the legacy import path re-exports the real executor.

``agent_foundry.acp.agent_runner.run_agent_in_container`` must be the
same object as the real implementation from
``agent_foundry.orchestration.container_executor`` — any future refactor
that accidentally re-introduces a stub will fail here.
"""

from __future__ import annotations


def test_run_agent_in_container_is_real_executor() -> None:
    from agent_foundry.acp.agent_runner import run_agent_in_container
    from agent_foundry.orchestration.container_executor import (
        run_agent_in_container as real_impl,
    )

    assert run_agent_in_container is real_impl
