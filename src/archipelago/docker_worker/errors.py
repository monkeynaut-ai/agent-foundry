"""Error classes for the Docker worker subsystem.

Re-exports from Agent Container Protocol. Archipelago code should import
from here for backward compatibility; new code should import from
agent_foundry.acp.errors directly.
"""

from agent_foundry.acp.errors import (  # noqa: F401
    AdapterError,
    ContainerCreationError,
    ContainerLifecycleError,
    ProtocolError,
    SessionError,
)
