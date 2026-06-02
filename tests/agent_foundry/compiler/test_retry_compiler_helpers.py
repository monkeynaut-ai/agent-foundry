"""Unit tests for the module-level pure helpers lifted out of ``_compile_retry``.

These exercise the routing-marker read, exhaustion-reason derivation, disposition
coercion, and body-outcome evaluation directly, without compiling/invoking a graph.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agent_foundry.compiler.primitive_compiler import (
    DISPOSITION_KEY,
    _coerce_disposition,
    _derive_exhaustion_reason,
    _outcome_from_body,
    _read_retry_route,
    _reentry_route_key,
    _retry_route_key,
)
from agent_foundry.primitives.errors import PrimitiveCompilationError
from agent_foundry.primitives.retry_types import (
    AttemptOutcome,
    DispositionKind,
    ResolverDisposition,
    RetryExhaustionReason,
    RetryRoute,
)


class _RetryIn(BaseModel):
    n: int = 0
    done: bool = False


class _BodyOut(BaseModel):
    n: int = 0


# --- route key builders ---------------------------------------------------


def test_route_key_builders_are_prefix_namespaced() -> None:
    assert _retry_route_key("root_step0") == "root_step0__retry_route"
    assert _reentry_route_key("root_step0") == "root_step0__reentry_route"


# --- _read_retry_route -----------------------------------------------------


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (RetryRoute.PASS, RetryRoute.PASS),
        (RetryRoute.EXHAUSTED, RetryRoute.EXHAUSTED),
        (RetryRoute.NOT_PASSED, RetryRoute.NOT_PASSED),
        ("pass", RetryRoute.PASS),  # raw string round-trips through StrEnum
    ],
)
def test_read_retry_route_returns_marker(stored: object, expected: RetryRoute) -> None:
    state = {"k": stored}
    assert _read_retry_route(state, "k", "node") is expected


def test_read_retry_route_raises_when_absent() -> None:
    with pytest.raises(PrimitiveCompilationError, match="missing route marker 'k'"):
        _read_retry_route({}, "k", "node")


def test_read_retry_route_raises_on_unknown_value() -> None:
    with pytest.raises(ValueError):
        _read_retry_route({"k": "bogus"}, "k", "node")


# --- _derive_exhaustion_reason --------------------------------------------


def test_exhaustion_reason_body_exceptions_only() -> None:
    assert _derive_exhaustion_reason(raised=3, clean_not_passed=0) is (
        RetryExhaustionReason.BODY_EXCEPTIONS
    )


def test_exhaustion_reason_condition_not_met_only() -> None:
    assert _derive_exhaustion_reason(raised=0, clean_not_passed=3) is (
        RetryExhaustionReason.CONDITION_NOT_MET
    )


@pytest.mark.parametrize(
    ("raised", "clean"),
    [(2, 1), (1, 2), (0, 0)],
)
def test_exhaustion_reason_mixed_or_neither_falls_to_mixed(raised: int, clean: int) -> None:
    assert _derive_exhaustion_reason(raised, clean) is RetryExhaustionReason.MIXED


# --- _coerce_disposition ---------------------------------------------------


def test_coerce_disposition_passthrough_instance() -> None:
    disp = ResolverDisposition(kind=DispositionKind.ACCEPT)
    assert _coerce_disposition(disp) is disp


def test_coerce_disposition_from_dump() -> None:
    raw = ResolverDisposition(kind=DispositionKind.ABORT, reason="nope").model_dump()
    coerced = _coerce_disposition(raw)
    assert coerced.kind is DispositionKind.ABORT
    assert coerced.reason == "nope"


def test_disposition_key_constant() -> None:
    assert DISPOSITION_KEY == "disposition"


# --- _outcome_from_body ----------------------------------------------------


def test_outcome_from_body_passed_when_until_true() -> None:
    state = {"n": 0, "done": False}
    merged, outcome = _outcome_from_body(
        state,
        {"n": 5},
        body_out=_BodyOut,
        retry_in=_RetryIn,
        retry_id="r",
        until_fn=lambda m: m.n >= 5,
    )
    assert outcome is AttemptOutcome.PASSED
    assert merged["n"] == 5
    # Original state is not mutated.
    assert state["n"] == 0


def test_outcome_from_body_not_passed_when_until_false() -> None:
    _merged, outcome = _outcome_from_body(
        {"n": 0},
        {"n": 1},
        body_out=_BodyOut,
        retry_in=_RetryIn,
        retry_id="r",
        until_fn=lambda m: m.n >= 5,
    )
    assert outcome is AttemptOutcome.NOT_PASSED
