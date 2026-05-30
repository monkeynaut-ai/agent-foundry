"""Synthetic end-to-end tests for the Retry resolver seat (AC #5/#6/#7).

A self-contained workflow mirroring the design-review pattern with NO
Archipelago dependency:

  - a "designer" body FunctionAction produces an artifact plus an automated
    verdict;
  - the automated reviewer always fails — ``until`` checks the automated
    verdict, which stays "fail" until the resolver supplies guidance;
  - a resolver (a non-gate participant) contributes a guidance verdict and a
    disposition; on RETRY the body re-runs, reads the resolver's guidance, and
    then passes.

These tests exercise the resolver seat as a general capability: an ordinary
FunctionAction and a callable-class instance both fill the role with zero
change to the primitive or compiler.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import BaseModel

from agent_foundry.compiler.primitive_compiler import compile_runtime_plan, get_type_args
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.orchestration.lifecycle_writer import LifecycleWriter
from agent_foundry.primitives.models import FunctionAction, Retry
from agent_foundry.primitives.plan import PrimitivePlan
from agent_foundry.primitives.retry_types import (
    DispositionKind,
    ResolverDisposition,
    RetryAborted,
)

# ---------------------------------------------------------------------------
# Workflow state
# ---------------------------------------------------------------------------


class W(BaseModel):
    """Synthetic design-review state.

    ``artifact`` is what the designer body produces; ``automated_verdict`` is the
    machine reviewer's call (starts "fail"); ``guidance`` is what the resolver
    supplies and the body reads on a re-run.
    """

    artifact: str = ""
    automated_verdict: str = "fail"
    guidance: str = ""
    body_runs: int = 0
    disposition: ResolverDisposition | None = None


# ---------------------------------------------------------------------------
# Capturing lifecycle writer (mirrors test_retry_exception_policy)
# ---------------------------------------------------------------------------


@dataclass
class _CapturingWriter(LifecycleWriter):
    events: list[dict] = field(default_factory=list)

    def append(self, event_type: LifecycleEvent, **fields: Any) -> None:
        self.events.append({"type": event_type, **fields})

    def append_run_event(self, kind: str, **fields: Any) -> None:
        pass

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Run-context + compile-and-run helpers (mirrors test_retry_resolver)
# ---------------------------------------------------------------------------


def _run_context(writer: LifecycleWriter | None = None):
    import pathlib
    import tempfile

    from agent_foundry.orchestration.run_context import (
        NoOpLifecycleWriter,
        RunContext,
        current_run_context,
    )

    ctx = RunContext(
        run_id="retry-resolver-e2e",
        artifacts_dir=pathlib.Path(tempfile.mkdtemp()),
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=writer or NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    return current_run_context, ctx


async def _compile_and_run(retry: Retry, initial: W, writer: LifecycleWriter | None = None) -> W:
    ctx_var, ctx = _run_context(writer)
    token = ctx_var.set(ctx)
    try:
        _, root_out = get_type_args(retry)
        graph = compile_runtime_plan(PrimitivePlan(root=retry))
        result = await graph.ainvoke(initial.model_dump())
        return root_out.model_validate(result)
    finally:
        ctx_var.reset(token)


# ---------------------------------------------------------------------------
# The designer body — produces an artifact + automated verdict. The automated
# reviewer always fails until the resolver's guidance is present, at which point
# a re-run reads the guidance and the automated verdict passes.
# ---------------------------------------------------------------------------


def _designer_body(sink: dict) -> FunctionAction:
    """Body that produces an artifact and an automated verdict.

    ``sink["runs"]`` counts every body execution (automated + re-entries). The
    automated verdict passes only once the resolver has written ``guidance``.
    """

    def _fn(s: W) -> W:
        sink["runs"] += 1
        verdict = "pass" if s.guidance else "fail"
        artifact = f"design-v{s.body_runs + 1}"
        return W(
            artifact=artifact,
            automated_verdict=verdict,
            guidance=s.guidance,
            body_runs=s.body_runs + 1,
            disposition=s.disposition,
        )

    return FunctionAction[W, W](function=_fn)


# ---------------------------------------------------------------------------
# AC #6 / #7 — plain FunctionAction resolver (general capability, no Archipelago)
# ---------------------------------------------------------------------------


# Distinct diagnostic label for the resolver node so its lifecycle events can be
# positively identified among the body events (which carry their node_id).
RESOLVER_NODE_NAME = "resolver-node"


def _function_resolver(sink: dict) -> FunctionAction:
    """Resolver as a plain function: RETRY (with guidance) on first visit, then
    ACCEPT if revisited. The continue/accept state is the resolver's own merged
    output — no nested state carried on the disposition."""

    def _fn(s: W) -> W:
        sink["resolver_visits"] += 1
        first = sink["resolver_visits"] == 1
        kind = DispositionKind.RETRY if first else DispositionKind.ACCEPT
        return W(
            artifact=s.artifact,
            automated_verdict=s.automated_verdict,
            guidance="reviewer-supplied-guidance",
            body_runs=s.body_runs,
            disposition=ResolverDisposition(kind=kind, reason="guided"),
        )

    return FunctionAction[W, W](function=_fn, name=RESOLVER_NODE_NAME)


@pytest.mark.asyncio
async def test_function_resolver_retry_then_body_passes() -> None:
    """A FunctionAction resolver RETRYs once with guidance; the body re-runs,
    reads the guidance, and the automated verdict passes. The cycle terminates
    cleanly (no exception) and downstream sees the passing artifact."""
    body_sink = {"runs": 0}
    resolver_sink = {"resolver_visits": 0}

    retry = Retry[W, W](
        max_attempts=1,
        until=lambda s: s.automated_verdict == "pass",
        body=_designer_body(body_sink),
        on_max_attempts_resolver=_function_resolver(resolver_sink),
    )
    result = await _compile_and_run(retry, W())

    # 1 automated attempt + exactly 1 RETRY re-entry = 2 body runs.
    assert body_sink["runs"] == 2
    # The resolver was visited exactly once (RETRY); the re-run passed until() so
    # it exited via the success path without bouncing back.
    assert resolver_sink["resolver_visits"] == 1
    # Downstream sees the passing automated verdict and the re-run artifact.
    assert result.automated_verdict == "pass"
    assert result.artifact == "design-v2"
    assert result.guidance == "reviewer-supplied-guidance"


# ---------------------------------------------------------------------------
# AC #7 — callable-class resolver (polymorphism, zero change to Retry/compiler)
# ---------------------------------------------------------------------------


class DeterministicResolver:
    """A non-function, non-gate participant filling the resolver role.

    ``__call__`` returns RETRY (with guidance) on the first visit and ACCEPT
    thereafter — the same contract as the plain-function resolver, proving the
    seat is polymorphic over any ``(state) -> state`` callable."""

    def __init__(self, guidance: str) -> None:
        self._guidance = guidance
        self.visits = 0

    def __call__(self, s: W) -> W:
        self.visits += 1
        kind = DispositionKind.RETRY if self.visits == 1 else DispositionKind.ACCEPT
        return W(
            artifact=s.artifact,
            automated_verdict=s.automated_verdict,
            guidance=self._guidance,
            body_runs=s.body_runs,
            disposition=ResolverDisposition(kind=kind, reason="guided"),
        )


@pytest.mark.asyncio
async def test_callable_class_resolver_matches_function_behavior() -> None:
    """A callable-class instance wrapped in FunctionAction fills the resolver seat
    with identical re-entry/termination behavior — zero change to the primitive."""
    body_sink = {"runs": 0}
    resolver = DeterministicResolver(guidance="reviewer-supplied-guidance")

    retry = Retry[W, W](
        max_attempts=1,
        until=lambda s: s.automated_verdict == "pass",
        body=_designer_body(body_sink),
        on_max_attempts_resolver=FunctionAction[W, W](function=resolver),
    )
    result = await _compile_and_run(retry, W())

    assert body_sink["runs"] == 2
    assert resolver.visits == 1
    assert result.automated_verdict == "pass"
    assert result.artifact == "design-v2"
    assert result.guidance == "reviewer-supplied-guidance"


# ---------------------------------------------------------------------------
# AC #5 — artifact / lifecycle fidelity: the resolver is a compiled node and so
# traverses the standard state-merge + lifecycle-event path. Its FunctionAction
# emits the SAME kind/shape of events as any body FunctionAction node.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_emits_same_lifecycle_shape_as_body_node() -> None:
    """The resolver FunctionAction emits FUNCTION_ACTION_STARTED/_COMPLETED with
    the same field shape as the body FunctionAction node — confirming it is a
    standard compiled node on the state-merge + lifecycle path, not a special
    case bolted onto the primitive."""
    writer = _CapturingWriter()
    body_sink = {"runs": 0}
    resolver_sink = {"resolver_visits": 0}

    retry = Retry[W, W](
        max_attempts=1,
        until=lambda s: s.automated_verdict == "pass",
        body=_designer_body(body_sink),
        on_max_attempts_resolver=_function_resolver(resolver_sink),
    )
    await _compile_and_run(retry, W(), writer=writer)

    started = [e for e in writer.events if e["type"] == LifecycleEvent.FUNCTION_ACTION_STARTED]
    completed = [e for e in writer.events if e["type"] == LifecycleEvent.FUNCTION_ACTION_COMPLETED]

    # Every started event carries the same field shape (node_id + name) whether
    # it is a body step or the resolver step.
    assert started, "expected FUNCTION_ACTION_STARTED events"
    for e in started:
        assert set(e) == {"type", "node_id", "name"}
    for e in completed:
        assert set(e) == {"type", "node_id", "name"}

    # Node ids of started and completed events match one-to-one: the resolver
    # node opened and closed exactly like a body node, with no FAILED event.
    assert sorted(e["node_id"] for e in started) == sorted(e["node_id"] for e in completed)
    assert not [e for e in writer.events if e["type"] == LifecycleEvent.FUNCTION_ACTION_FAILED]

    # Positively identify the resolver node on the lifecycle path: its distinct
    # label appears in BOTH a STARTED and a COMPLETED event. A silently
    # non-emitting resolver would leave this label absent and fail the test —
    # the two body runs alone cannot supply it (they carry their node_id as the
    # name, never RESOLVER_NODE_NAME).
    assert RESOLVER_NODE_NAME in {e["name"] for e in started}, (
        "resolver node did not emit a FUNCTION_ACTION_STARTED event"
    )
    assert RESOLVER_NODE_NAME in {e["name"] for e in completed}, (
        "resolver node did not emit a FUNCTION_ACTION_COMPLETED event"
    )

    # Distinct FunctionAction nodes fired: the two body executions (automated +
    # re-entry) plus the resolver — i.e. the resolver is one node among several
    # of the same kind, not a privileged path.
    body_node_ids = {e["node_id"] for e in started}
    assert len(body_node_ids) >= 2


# ---------------------------------------------------------------------------
# Contract guard — ACCEPT on first visit exits with the resolver's OWN merged
# output (no nested state on the disposition) without re-running the body.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_accept_exits_with_resolver_merged_state() -> None:
    """A resolver that ACCEPTs on the first visit exits the Retry with its own
    merged output; the body is not re-run and no exception is raised."""
    body_sink = {"runs": 0}

    def _accept(s: W) -> W:
        return W(
            artifact="resolver-final",
            automated_verdict=s.automated_verdict,
            guidance=s.guidance,
            body_runs=s.body_runs,
            disposition=ResolverDisposition(kind=DispositionKind.ACCEPT, reason="ok"),
        )

    retry = Retry[W, W](
        max_attempts=1,
        until=lambda s: s.automated_verdict == "pass",
        body=_designer_body(body_sink),
        on_max_attempts_resolver=FunctionAction[W, W](function=_accept),
    )
    result = await _compile_and_run(retry, W())

    # Only the single automated body attempt ran; ACCEPT did not re-enter.
    assert body_sink["runs"] == 1
    assert result.artifact == "resolver-final"


@pytest.mark.asyncio
async def test_resolver_abort_raises_without_reentry() -> None:
    """A resolver that ABORTs raises RetryAborted carrying its reason; the body
    is not re-run."""
    body_sink = {"runs": 0}

    def _abort(s: W) -> W:
        return W(
            artifact=s.artifact,
            automated_verdict=s.automated_verdict,
            guidance=s.guidance,
            body_runs=s.body_runs,
            disposition=ResolverDisposition(kind=DispositionKind.ABORT, reason="cannot-converge"),
        )

    retry = Retry[W, W](
        max_attempts=1,
        until=lambda s: s.automated_verdict == "pass",
        body=_designer_body(body_sink),
        on_max_attempts_resolver=FunctionAction[W, W](function=_abort),
    )
    with pytest.raises(RetryAborted, match="cannot-converge"):
        await _compile_and_run(retry, W())
    assert body_sink["runs"] == 1
