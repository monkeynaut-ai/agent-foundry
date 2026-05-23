"""``Runner`` Protocol — contract every execution backend satisfies.

A runner takes an :class:`EvalSuite` plus a target-bound task callable
and returns a :class:`RunResult` containing one entry per
``(case, invocation)`` pair.

This module is part of the declarative model layer — it imports no
third-party eval library. Concrete implementations live in
:mod:`agent_foundry.evals.runners`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from agent_foundry.evals.models.report import RunResult
from agent_foundry.evals.models.suite import EvalSuite

type Task = Callable[[Any], Awaitable[Any]]


class Runner(Protocol):
    """Execute a suite against a target-bound task and return a typed result."""

    async def run(
        self,
        suite: EvalSuite,
        *,
        task: Task,
        max_concurrency: int = 1,
    ) -> RunResult:
        """Execute ``suite``'s dataset against ``task`` and return a typed result.

        Implementations apply ``suite.invocations_per_case`` repeats and
        run cases with at most ``max_concurrency`` in flight. Each case's
        output is scored against the dataset's evaluators. Cases whose
        task call raises are captured in :attr:`EvaluationReport.failures`
        rather than aborting the run.
        """
        ...
