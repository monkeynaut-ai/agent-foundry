"""Public framework surface for Agent Foundry.

The top-level package exports the common building blocks needed to declare and
run typed processes. Specialized seams remain available from their subpackages,
for example ``agent_foundry.ai_models`` and ``agent_foundry.telemetry``.
"""

from __future__ import annotations

from typing import Any

from agent_foundry.constructs import (
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
    Sequence,
)
from agent_foundry.orchestration import (
    RunAborted,
    RunCompleted,
    RunFailed,
    RunOutcome,
)
from agent_foundry.responders import (
    Responder,
    ResponderProvider,
    StdinResponder,
    static_provider,
)

__all__ = [
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
    "Responder",
    "ResponderProvider",
    "Retry",
    "RunAborted",
    "RunCompleted",
    "RunFailed",
    "RunOutcome",
    "Sequence",
    "StdinResponder",
    "run_process",
    "static_provider",
]


def __getattr__(name: str) -> Any:
    if name == "run_process":
        from agent_foundry.orchestration import run_process as _run_process

        return _run_process
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
