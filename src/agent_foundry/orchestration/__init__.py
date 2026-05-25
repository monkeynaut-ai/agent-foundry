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
from agent_foundry.orchestration.summary import render_summary

if TYPE_CHECKING:
    from agent_foundry.orchestration.runner import run_primitive_plan

__all__ = [
    "AgentFailedError",
    "JsonlLifecycleWriter",
    "LifecycleEvent",
    "LifecycleWriter",
    "NoOpLifecycleWriter",
    "agent_log_path",
    "agent_turn_dir",
    "bootstrap_run_artifacts",
    "render_summary",
    "run_primitive_plan",
]


# runner.py imports compile_runtime_plan from primitive_compiler, which imports
# from orchestration.run_context. Eagerly importing runner here would create a
# cycle at module init time. Lazy __getattr__ breaks the cycle while keeping
# the public API intact.
def __getattr__(name: str) -> Any:
    if name == "run_primitive_plan":
        from agent_foundry.orchestration.runner import run_primitive_plan as _f

        return _f
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
