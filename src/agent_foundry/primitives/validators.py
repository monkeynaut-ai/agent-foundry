"""Graph-level type compatibility validation for primitives.

Uses a registry keyed by primitive type. Built-in primitives register
their validators at module import. Applications can define their own
Primitive subclasses and register validators for them via
``register_validator``.

Unknown primitive types raise ``UnregisteredPrimitiveError`` — silent
no-op fallback is rejected to prevent misconfiguration.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from agent_foundry.primitives.errors import (
    InvalidPromptKeyError,
    TypeMismatchError,
    UnregisteredPrimitiveError,
)
from agent_foundry.primitives.models import (
    AgentAction,
    Conditional,
    FunctionAction,
    GateAction,
    Loop,
    Primitive,
    Retry,
    Sequence,
    get_type_args,
)

# -- Registry --

type _ValidatorStorage = Callable[[Any], None]

_validator_registry: dict[type[Primitive], _ValidatorStorage] = {}


def register_validator[P: Primitive](
    prim_type: type[P],
    fn: Callable[[P], None],
) -> None:
    """Register a validator function for a primitive type.

    The function's parameter type is checked against ``prim_type`` at the
    call site, so ``register_validator(Sequence, _validate_sequence)``
    statically verifies ``_validate_sequence`` accepts ``Sequence``.

    Raises ``ValueError`` if a validator is already registered for
    ``prim_type``. This guards against accidental override of core
    validators by extension code or import-order bugs.
    """
    if prim_type in _validator_registry:
        raise ValueError(f"Validator already registered for {prim_type.__name__}")
    _validator_registry[prim_type] = cast(_ValidatorStorage, fn)


def validate_primitive(prim: Primitive) -> None:
    """Validate a primitive (and recursively, its children).

    Walks the type's MRO so a validator registered for a parent class
    handles subclasses unless a subclass has its own entry.

    Raises ``UnregisteredPrimitiveError`` if no validator is registered
    for any class in the primitive's MRO.
    """
    prim_type = type(prim)
    for cls in prim_type.__mro__:
        fn = _validator_registry.get(cls)
        if fn is not None:
            fn(prim)
            return
    raise UnregisteredPrimitiveError(
        f"No validator registered for {prim_type.__name__}; "
        f"register one with register_validator(...)",
        primitive_type=prim_type,
    )


# -- Helpers --


def _types_match(a: type, b: type) -> bool:
    """Check if two types are exactly the same (no subtype checks)."""
    return a is b


def _fields_available(required_type: type, available_fields: set[str], position: str) -> None:
    """Validate that all fields of required_type are present in available_fields."""
    required_fields = set(required_type.model_fields.keys())
    missing = required_fields - available_fields
    if missing:
        raise TypeMismatchError(
            message=(
                f"{position}: {required_type.__name__} requires fields "
                f"{sorted(missing)} not available in accumulated state "
                f"(available: {sorted(available_fields)})"
            ),
            expected=required_type,
            actual=required_type,
            position=position,
        )


# -- Per-type validators --


def _validate_sequence(seq: Sequence) -> None:
    seq_in, seq_out = get_type_args(seq)
    step_types = [get_type_args(s) for s in seq.steps]

    accumulated_fields = set(seq_in.model_fields.keys())

    for i, (step_in, step_out) in enumerate(step_types):
        _fields_available(step_in, accumulated_fields, f"Sequence step {i} input")
        accumulated_fields |= set(step_out.model_fields.keys())

    _fields_available(seq_out, accumulated_fields, "Sequence output")

    for step in seq.steps:
        validate_primitive(step)


def _validate_loop(loop: Loop) -> None:
    # Loop body type compatibility is deferred to the compiler (CS3).
    validate_primitive(loop.body)


def _validate_retry(retry: Retry) -> None:
    retry_in, retry_out = get_type_args(retry)
    body_in, body_out = get_type_args(retry.body)

    if not _types_match(retry_in, body_in):
        raise TypeMismatchError(
            message=(
                f"Retry body input type {body_in.__name__} "
                f"does not match Retry input type {retry_in.__name__}"
            ),
            expected=retry_in,
            actual=body_in,
            position="Retry body input",
        )

    if not _types_match(retry_out, body_out):
        raise TypeMismatchError(
            message=(
                f"Retry body output type {body_out.__name__} "
                f"does not match Retry output type {retry_out.__name__}"
            ),
            expected=retry_out,
            actual=body_out,
            position="Retry body output",
        )

    if not _types_match(body_in, body_out):
        raise TypeMismatchError(
            message=(
                f"Retry body output type {body_out.__name__} "
                f"does not match body input type {body_in.__name__} "
                f"for re-entry on next attempt"
            ),
            expected=body_in,
            actual=body_out,
            position="Retry body re-entry",
        )

    validate_primitive(retry.body)


def _validate_conditional(cond: Conditional) -> None:
    cond_in, cond_out = get_type_args(cond)
    then_in, then_out = get_type_args(cond.then_branch)

    if cond.else_branch is None:
        if not _types_match(cond_in, cond_out):
            raise TypeMismatchError(
                message=(
                    f"Conditional with no else_branch requires input and output "
                    f"types to match, got {cond_in.__name__} and {cond_out.__name__}"
                ),
                expected=cond_in,
                actual=cond_out,
                position="Conditional no else_branch: input != output",
            )

        if not _types_match(cond_in, then_in):
            raise TypeMismatchError(
                message=(
                    f"Conditional then_branch input type {then_in.__name__} "
                    f"does not match Conditional input type {cond_in.__name__}"
                ),
                expected=cond_in,
                actual=then_in,
                position="Conditional then_branch input",
            )

        if not _types_match(cond_in, then_out):
            raise TypeMismatchError(
                message=(
                    f"Conditional then_branch output type {then_out.__name__} "
                    f"does not match Conditional input type {cond_in.__name__}"
                ),
                expected=cond_in,
                actual=then_out,
                position="Conditional then_branch output",
            )
    else:
        if not _types_match(cond_in, then_in):
            raise TypeMismatchError(
                message=(
                    f"Conditional then_branch input type {then_in.__name__} "
                    f"does not match Conditional input type {cond_in.__name__}"
                ),
                expected=cond_in,
                actual=then_in,
                position="Conditional then_branch input",
            )

        if not _types_match(cond_out, then_out):
            raise TypeMismatchError(
                message=(
                    f"Conditional then_branch output type {then_out.__name__} "
                    f"does not match Conditional output type {cond_out.__name__}"
                ),
                expected=cond_out,
                actual=then_out,
                position="Conditional then_branch output",
            )

        else_in, else_out = get_type_args(cond.else_branch)

        if not _types_match(cond_in, else_in):
            raise TypeMismatchError(
                message=(
                    f"Conditional else_branch input type {else_in.__name__} "
                    f"does not match Conditional input type {cond_in.__name__}"
                ),
                expected=cond_in,
                actual=else_in,
                position="Conditional else_branch input",
            )

        if not _types_match(cond_out, else_out):
            raise TypeMismatchError(
                message=(
                    f"Conditional else_branch output type {else_out.__name__} "
                    f"does not match Conditional output type {cond_out.__name__}"
                ),
                expected=cond_out,
                actual=else_out,
                position="Conditional else_branch output",
            )

        validate_primitive(cond.else_branch)

    validate_primitive(cond.then_branch)


def _validate_gate_action(gate: GateAction) -> None:
    input_type, _ = get_type_args(gate)
    available = list(input_type.model_fields.keys())
    if gate.prompt_key not in available:
        raise InvalidPromptKeyError(
            message=(
                f"GateAction prompt_key '{gate.prompt_key}' not found in "
                f"{input_type.__name__}; available fields: {available}"
            ),
            prompt_key=gate.prompt_key,
            available_fields=available,
        )


def _validate_function_action(_action: FunctionAction) -> None:
    # FunctionAction has no graph-level constraints beyond Primitive
    # parameterization (enforced at construction).
    return


def _validate_agent_action(_action: AgentAction) -> None:
    # AgentAction is a leaf — no children to recurse into, no
    # graph-level constraints beyond Primitive parameterization.
    return


# -- Registration --

register_validator(Sequence, _validate_sequence)
register_validator(Loop, _validate_loop)
register_validator(Retry, _validate_retry)
register_validator(Conditional, _validate_conditional)
register_validator(GateAction, _validate_gate_action)
register_validator(FunctionAction, _validate_function_action)
register_validator(AgentAction, _validate_agent_action)
