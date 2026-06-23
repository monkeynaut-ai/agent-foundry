"""Orchestration package for agent-foundry run lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_foundry.orchestration.artifacts import (
    agent_log_path,
    agent_turn_dir,
    bootstrap_run_artifacts,
)
from agent_foundry.orchestration.errors import AgentFailedError
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.lifecycle_writer import (
    JsonlLifecycleWriter,
    LifecycleWriter,
    NoOpLifecycleWriter,
)
from agent_foundry.orchestration.run_outcome import (
    FailureKind,
    RunAborted,
    RunCompleted,
    RunFailed,
    RunOutcome,
    RunOutcomeKind,
)
from agent_foundry.orchestration.summary import render_summary

if TYPE_CHECKING:
    from agent_foundry.orchestration.runner import run_process

__all__ = [
    "AgentFailedError",
    "FailureKind",
    "JsonlLifecycleWriter",
    "LifecycleEvent",
    "LifecycleWriter",
    "NoOpLifecycleWriter",
    "RunAborted",
    "RunCompleted",
    "RunFailed",
    "RunOutcome",
    "RunOutcomeKind",
    "agent_log_path",
    "agent_turn_dir",
    "bootstrap_run_artifacts",
    "render_summary",
    "run_process",
]


# runner.py imports compile_process from compiler, which imports
# from orchestration.run_context. Eagerly importing runner here would create a
# cycle at module init time. Lazy __getattr__ breaks the cycle while keeping
# the public API intact.
def __getattr__(name: str) -> Any:
    if name == "run_process":
        from agent_foundry.orchestration.runner import run_process as _f

        return _f
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
