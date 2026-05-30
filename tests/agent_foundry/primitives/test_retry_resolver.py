"""Tests for the Retry resolver-cycle topology (operator-guided retry resolver seat).

The automated phase exhausts max_attempts without until() passing, then enters a
cycle of real outer-graph nodes: a resolver node emits a ResolverDisposition, a
disposition router routes ACCEPT -> exit, ABORT -> raise, RETRY -> re-run body
once and re-evaluate until(). A RETRY re-run that passes exits via the same
success exit as the automated pass path; one that still fails returns to the
resolver. With no resolver configured, exhaustion fails closed to ABORT.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from agent_foundry.compiler.primitive_compiler import compile_runtime_plan, get_type_args
from agent_foundry.primitives.errors import PrimitiveCompilationError
from agent_foundry.primitives.models import (
    FunctionAction,
    GateAction,
    Retry,
    RetryExceptionPolicy,
    Sequence,
)
from agent_foundry.primitives.plan import PrimitivePlan
from agent_foundry.primitives.retry_types import (
    DispositionKind,
    ResolverDidNotConvergeError,
    ResolverDisposition,
    RetryAborted,
)

# ---------------------------------------------------------------------------
# State model
# ---------------------------------------------------------------------------


class RS(BaseModel):
    n: int = 0
    verdict: str = "fail"
    disposition: ResolverDisposition | None = None


# ---------------------------------------------------------------------------
# Run-context + compile-and-run helpers (mirrors test_retry_exception_policy)
# ---------------------------------------------------------------------------


def _run_context():
    import pathlib
    import tempfile

    from agent_foundry.orchestration.run_context import (
        NoOpLifecycleWriter,
        RunContext,
        current_run_context,
    )

    ctx = RunContext(
        run_id="retry-resolver-test",
        artifacts_dir=pathlib.Path(tempfile.mkdtemp()),
        container_registry=object(),
        responder_provider=object(),
        lifecycle_writer=NoOpLifecycleWriter(),
        cancel_event=asyncio.Event(),
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"},
    )
    return current_run_context, ctx


async def _compile_and_run(retry: Retry, initial: RS) -> RS:
    ctx_var, ctx = _run_context()
    token = ctx_var.set(ctx)
    try:
        _, root_out = get_type_args(retry)
        graph = compile_runtime_plan(PrimitivePlan(root=retry))
        result = await graph.ainvoke(initial.model_dump())
        return root_out.model_validate(result)
    finally:
        ctx_var.reset(token)


def _failing_body() -> FunctionAction:
    """Body that increments n but never satisfies until() (verdict stays fail)."""
    return FunctionAction[RS, RS](
        function=lambda s: RS(n=s.n + 1, verdict="fail", disposition=s.disposition)
    )


def _resolver(dispositions: list[DispositionKind], state_edit=None) -> FunctionAction:
    """Resolver that emits the next disposition from ``dispositions`` per call.

    Optional ``state_edit(s) -> dict`` supplies extra state fields written
    alongside the disposition (e.g. flipping verdict so a RETRY re-run passes).
    """
    calls = {"i": 0}

    def _fn(s: RS) -> RS:
        i = calls["i"]
        calls["i"] += 1
        kind = dispositions[min(i, len(dispositions) - 1)]
        edits = state_edit(s) if state_edit is not None else {}
        base = {"n": s.n, "verdict": s.verdict}
        base.update(edits)
        return RS(disposition=ResolverDisposition(kind=kind, reason="r"), **base)

    fn = FunctionAction[RS, RS](function=_fn)
    fn._calls = calls  # type: ignore[attr-defined]
    return fn


# ---------------------------------------------------------------------------
# AC1 — RETRY re-runs the body once, re-evaluates until()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac1_retry_then_body_reenters_once_still_failing() -> None:
    """RETRY re-runs the body exactly once; the re-run still fails until(), so
    control returns to the resolver (it does not run a second body before the
    resolver gets to disposition again). Resolver then ACCEPTs to terminate."""
    body_calls = {"n": 0}

    def _body(s: RS) -> RS:
        body_calls["n"] += 1
        return RS(n=s.n + 1, verdict="fail", disposition=s.disposition)

    retry = Retry[RS, RS](
        max_attempts=1,
        until=lambda s: s.verdict == "pass",
        body=FunctionAction[RS, RS](function=_body),
        on_max_attempts_resolver=_resolver([DispositionKind.RETRY, DispositionKind.ACCEPT]),
    )
    await _compile_and_run(retry, RS(n=0))
    # 1 automated attempt + exactly 1 re-entry = 2 body runs.
    assert body_calls["n"] == 2


@pytest.mark.asyncio
async def test_ac1_retry_reentry_that_passes_exits_successfully() -> None:
    """A RETRY re-run that PASSES until() exits via the success exit and does NOT
    bounce back to the resolver. The resolver runs exactly once and downstream
    sees the passing output."""
    resolver = _resolver(
        [DispositionKind.RETRY],
        state_edit=lambda s: {"verdict": "pass"},
    )
    retry = Retry[RS, RS](
        max_attempts=1,
        until=lambda s: s.verdict == "pass",
        body=FunctionAction[RS, RS](
            function=lambda s: RS(n=s.n + 1, verdict=s.verdict, disposition=s.disposition)
        ),
        on_max_attempts_resolver=resolver,
    )
    result = await _compile_and_run(retry, RS(n=0))
    assert result.verdict == "pass"
    assert resolver._calls["i"] == 1  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC2 — ACCEPT exits with supplied state; ABORT terminates without re-exec
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac2_accept_exits_with_supplied_state() -> None:
    """ACCEPT exits the Retry; downstream sees the resolver-supplied state."""
    resolver = _resolver(
        [DispositionKind.ACCEPT],
        state_edit=lambda s: {"n": 999},
    )
    retry = Retry[RS, RS](
        max_attempts=1,
        until=lambda s: False,
        body=_failing_body(),
        on_max_attempts_resolver=resolver,
    )
    result = await _compile_and_run(retry, RS(n=0))
    assert result.n == 999


@pytest.mark.asyncio
async def test_ac2_abort_terminates_without_body_reexec() -> None:
    """ABORT raises RetryAborted carrying the reason; body is not re-executed."""
    body_calls = {"n": 0}

    def _body(s: RS) -> RS:
        body_calls["n"] += 1
        return RS(n=s.n + 1, verdict="fail", disposition=s.disposition)

    retry = Retry[RS, RS](
        max_attempts=1,
        until=lambda s: False,
        body=FunctionAction[RS, RS](function=_body),
        on_max_attempts_resolver=_resolver([DispositionKind.ABORT]),
    )
    with pytest.raises(RetryAborted, match="r"):
        await _compile_and_run(retry, RS(n=0))
    assert body_calls["n"] == 1  # only the automated attempt; no re-entry


# ---------------------------------------------------------------------------
# AC3 — cycle repeats until ACCEPT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac3_resolver_cycle_repeats_until_accept() -> None:
    """RETRY -> re-run NOT_PASSED -> resolver -> RETRY -> ... -> ACCEPT ends the cycle."""
    resolver = _resolver([DispositionKind.RETRY, DispositionKind.RETRY, DispositionKind.ACCEPT])
    retry = Retry[RS, RS](
        max_attempts=1,
        until=lambda s: False,
        body=_failing_body(),
        on_max_attempts_resolver=resolver,
    )
    result = await _compile_and_run(retry, RS(n=0))
    # 3 resolver visits (RETRY, RETRY, ACCEPT).
    assert resolver._calls["i"] == 3  # type: ignore[attr-defined]
    # 1 automated + 2 re-entries.
    assert result.n == 3


# ---------------------------------------------------------------------------
# AC4 — fail-closed with no resolver; legacy-equivalent pass path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac4_no_resolver_fails_closed_aborts() -> None:
    """Exhaustion with no resolver configured fails closed -> RetryAborted."""
    retry = Retry[RS, RS](
        max_attempts=2,
        until=lambda s: False,
        body=_failing_body(),
    )
    with pytest.raises(RetryAborted):
        await _compile_and_run(retry, RS(n=0))


@pytest.mark.asyncio
async def test_ac4_body_passes_within_attempts_behaves_as_today() -> None:
    """A passing body never reaches exhaustion; result is the passing output."""
    retry = Retry[RS, RS](
        max_attempts=3,
        until=lambda s: s.verdict == "pass",
        body=FunctionAction[RS, RS](
            function=lambda s: RS(n=s.n + 1, verdict="pass", disposition=s.disposition)
        ),
    )
    result = await _compile_and_run(retry, RS(n=0))
    assert result.verdict == "pass"
    assert result.n == 1


# ---------------------------------------------------------------------------
# AC8 — exception handling identical across automated + re-entry paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac8_exception_in_automated_attempt_is_not_passed() -> None:
    """Under CATCH_AND_CONTINUE a body raise is one NOT_PASSED automated attempt;
    exhaustion then routes to the resolver, which ACCEPTs."""
    retry = Retry[RS, RS](
        max_attempts=1,
        until=lambda s: s.verdict == "pass",
        body=_raising_body(RuntimeError("boom")),
        exception_policy=RetryExceptionPolicy.CATCH_AND_CONTINUE,
        on_max_attempts_resolver=_resolver([DispositionKind.ACCEPT]),
    )
    # Exhaustion reached without an unhandled raise -> resolver ACCEPT -> exit.
    result = await _compile_and_run(retry, RS(n=7))
    assert result.n == 7  # snapshot restored after the raising attempt


@pytest.mark.asyncio
async def test_ac8_exception_in_retry_reentry_identical() -> None:
    """A body raise during a RETRY re-entry is handled by the SAME path. Under
    PROPAGATE the raise propagates in BOTH the automated and re-entry cases —
    assert the same exception surfaces both ways."""
    # Automated case: PROPAGATE raise surfaces directly.
    automated = Retry[RS, RS](
        max_attempts=1,
        until=lambda s: s.verdict == "pass",
        body=_raising_body(ValueError("same-exc")),
        exception_policy=RetryExceptionPolicy.PROPAGATE,
    )
    with pytest.raises(ValueError, match="same-exc"):
        await _compile_and_run(automated, RS(n=0))

    # Re-entry case: first automated attempt fails (no raise), resolver RETRYs,
    # then the re-entry body raises under PROPAGATE -> same exception surfaces.
    flip = {"first": True}

    def _body(s: RS) -> RS:
        if flip["first"]:
            flip["first"] = False
            return RS(n=s.n, verdict="fail", disposition=s.disposition)
        raise ValueError("same-exc")

    reentry = Retry[RS, RS](
        max_attempts=1,
        until=lambda s: s.verdict == "pass",
        body=FunctionAction[RS, RS](function=_body),
        exception_policy=RetryExceptionPolicy.PROPAGATE,
        on_max_attempts_resolver=_resolver([DispositionKind.RETRY]),
    )
    with pytest.raises(ValueError, match="same-exc"):
        await _compile_and_run(reentry, RS(n=0))


# ---------------------------------------------------------------------------
# AC9 — backstop raises a distinct error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ac9_backstop_raises_distinct_error() -> None:
    """A resolver that always RETRYs hits resolver_max_reentries and raises
    ResolverDidNotConvergeError — which is NOT a RetryAborted."""
    retry = Retry[RS, RS](
        max_attempts=1,
        until=lambda s: False,
        body=_failing_body(),
        on_max_attempts_resolver=_resolver([DispositionKind.RETRY]),
        resolver_max_reentries=3,
    )
    with pytest.raises(ResolverDidNotConvergeError) as exc_info:
        await _compile_and_run(retry, RS(n=0))
    assert not isinstance(exc_info.value, RetryAborted)


@pytest.mark.asyncio
async def test_ac9_backstop_runs_exactly_max_reentries_bodies() -> None:
    """With resolver_max_reentries=3 and an always-RETRY resolver, EXACTLY 3
    re-entry body runs occur before ResolverDidNotConvergeError is raised. This
    pins the backstop ``>`` boundary: a flip to ``>=`` would fire one re-entry
    early (only 2 re-entry bodies) and silently fail this assertion."""
    body_calls = {"n": 0}

    def _body(s: RS) -> RS:
        body_calls["n"] += 1
        return RS(n=s.n + 1, verdict="fail", disposition=s.disposition)

    resolver = _resolver([DispositionKind.RETRY])
    retry = Retry[RS, RS](
        max_attempts=1,
        until=lambda s: False,
        body=FunctionAction[RS, RS](function=_body),
        on_max_attempts_resolver=resolver,
        resolver_max_reentries=3,
    )
    with pytest.raises(ResolverDidNotConvergeError):
        await _compile_and_run(retry, RS(n=0))
    # 1 automated body + exactly 3 re-entry bodies; the 4th re-entry trips the
    # backstop before running the body.
    assert body_calls["n"] == 4
    # Resolver visited once per exhaustion: automated + each of the 3 re-entries.
    assert resolver._calls["i"] == 4  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Disposition shape contract — router raises PrimitiveCompilationError when a
# resolver's output is not a coercible ResolverDisposition (validator does not
# check resolver output, so this is only reachable at runtime).
# ---------------------------------------------------------------------------


class NoDispState(BaseModel):
    n: int = 0
    verdict: str = "fail"


class StrDispState(BaseModel):
    n: int = 0
    verdict: str = "fail"
    disposition: str = "garbage"


@pytest.mark.asyncio
async def test_resolver_output_without_disposition_field_raises() -> None:
    """A resolver whose output model has NO 'disposition' field leaves state's
    disposition unset; the router raises PrimitiveCompilationError."""
    resolver = FunctionAction[RS, NoDispState](
        function=lambda s: NoDispState(n=s.n, verdict=s.verdict)
    )
    retry = Retry[RS, RS](
        max_attempts=1,
        until=lambda s: False,
        body=_failing_body(),
        on_max_attempts_resolver=resolver,
    )
    with pytest.raises(
        PrimitiveCompilationError,
        match="resolver produced no 'disposition' field",
    ):
        await _compile_and_run(retry, RS(n=0))


@pytest.mark.asyncio
async def test_resolver_non_coercible_disposition_raises() -> None:
    """A resolver that writes a non-coercible 'disposition' (a bare string)
    fails coercion; the router raises PrimitiveCompilationError."""
    resolver = FunctionAction[RS, StrDispState](
        function=lambda s: StrDispState(n=s.n, verdict=s.verdict, disposition="garbage")
    )
    retry = Retry[RS, RS](
        max_attempts=1,
        until=lambda s: False,
        body=_failing_body(),
        on_max_attempts_resolver=resolver,
    )
    with pytest.raises(
        PrimitiveCompilationError,
        match="'disposition' is not a ResolverDisposition",
    ):
        await _compile_and_run(retry, RS(n=0))


# ---------------------------------------------------------------------------
# Sync RETRY path — the sync reentry_node_sync path (other tests use ainvoke).
# ---------------------------------------------------------------------------


def test_sync_invoke_routes_through_retry_reentry() -> None:
    """A sync ``invoke`` run goes through at least one RETRY re-entry: the
    resolver RETRYs once then ACCEPTs, exercising reentry_node_sync."""
    resolver = _resolver([DispositionKind.RETRY, DispositionKind.ACCEPT])
    retry = Retry[RS, RS](
        max_attempts=1,
        until=lambda s: False,
        body=_failing_body(),
        on_max_attempts_resolver=resolver,
    )
    ctx_var, ctx = _run_context()
    token = ctx_var.set(ctx)
    try:
        _, root_out = get_type_args(retry)
        graph = compile_runtime_plan(PrimitivePlan(root=retry))
        result = root_out.model_validate(graph.invoke(RS(n=0).model_dump()))
    finally:
        ctx_var.reset(token)
    # 2 resolver visits (RETRY, ACCEPT); 1 automated + 1 re-entry body => n == 2.
    assert resolver._calls["i"] == 2  # type: ignore[attr-defined]
    assert result.n == 2


# ---------------------------------------------------------------------------
# Gate resolver — real outer-graph interrupt + operator disposition routing
# ---------------------------------------------------------------------------


class TestGateResolver:
    def test_gate_resolver_pauses_then_operator_abort_routes(self) -> None:
        """REAL gate -> disposition path: the gate resolver pauses as an
        outer-graph node, the operator sets an ABORT disposition, resume routes
        to abort."""
        gate = GateAction[RS, RS](interaction="stdin", prompt_key="verdict")
        r = Retry[RS, RS](
            max_attempts=1,
            until=lambda s: False,
            body=FunctionAction[RS, RS](function=lambda s: s),
            on_max_attempts_resolver=gate,
        )
        graph = compile_runtime_plan(PrimitivePlan(root=r))
        config = {"configurable": {"thread_id": "gate-resolver-abort"}}
        graph.invoke({"verdict": "fail"}, config=config)
        snap = graph.get_state(config)
        assert snap.next  # paused before gate resolver -> outer-graph interrupt

        graph.update_state(
            config,
            {
                "disposition": ResolverDisposition(
                    kind=DispositionKind.ABORT, reason="operator declines"
                ).model_dump()
            },
        )
        with pytest.raises(RetryAborted, match="operator declines"):
            graph.invoke(None, config=config)

    def test_gate_resolver_pauses_then_operator_accept_routes(self) -> None:
        """Same outer-graph pause; operator sets ACCEPT -> resume exits with the
        merged state."""
        gate = GateAction[RS, RS](interaction="stdin", prompt_key="verdict")
        r = Retry[RS, RS](
            max_attempts=1,
            until=lambda s: False,
            body=FunctionAction[RS, RS](function=lambda s: s),
            on_max_attempts_resolver=gate,
        )
        graph = compile_runtime_plan(PrimitivePlan(root=r))
        config = {"configurable": {"thread_id": "gate-resolver-accept"}}
        graph.invoke({"verdict": "fail", "n": 5}, config=config)
        snap = graph.get_state(config)
        assert snap.next

        graph.update_state(
            config,
            {
                "verdict": "pass",
                "disposition": ResolverDisposition(kind=DispositionKind.ACCEPT).model_dump(),
            },
        )
        result = graph.invoke(None, config=config)
        assert result["verdict"] == "pass"
        assert result["n"] == 5


# ---------------------------------------------------------------------------
# State-channel pre-pass — nested Retry channels declared in outer schema
# ---------------------------------------------------------------------------


def test_nested_retry_channels_declared_in_outer_schema() -> None:
    """A Retry nested inside a Sequence step gets its namespaced backstop /
    exhaustion channels DECLARED in the outer state schema. This fails if the
    pre-pass prefix scheme diverges from the compiler's child-prefix scheme."""
    from agent_foundry.compiler.primitive_compiler import _collect_retry_channels

    inner_retry = Retry[RS, RS](
        max_attempts=1,
        until=lambda s: False,
        body=_failing_body(),
        on_max_attempts_resolver=_resolver([DispositionKind.ACCEPT]),
    )
    passthrough = FunctionAction[RS, RS](function=lambda s: s)
    seq = Sequence[RS, RS](steps=[passthrough, inner_retry])

    channels = _collect_retry_channels(seq, "root")
    # Sequence step 1 prefix is root_step_1; that retry's channels are namespaced under it.
    assert "root_step_1__resolver_reentries" in channels
    assert "root_step_1__exhaustion_reason" in channels
    assert "root_step_1__attempt_failures" in channels


def _raising_body(exc: Exception) -> FunctionAction:
    def _raise(s: RS) -> RS:
        raise exc

    return FunctionAction[RS, RS](function=_raise)
