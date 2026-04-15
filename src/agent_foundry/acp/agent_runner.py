"""Re-export of the container executor (F0 onward).

Plan 1 shipped this as a NotImplementedError stub. Phase F0 replaces
it with the real minimum-viable executor from
``orchestration.container_executor``. Phase F.4 (later) is now a no-op
reconfirmation rather than the first wiring point.
"""

from agent_foundry.orchestration.container_executor import run_agent_in_container

__all__ = ["run_agent_in_container"]
