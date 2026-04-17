"""Re-export of the container executor.

Legacy import path. The real implementation lives in
``agent_foundry.orchestration.container_executor``.
"""

from agent_foundry.orchestration.container_executor import run_agent_in_container

__all__ = ["run_agent_in_container"]
