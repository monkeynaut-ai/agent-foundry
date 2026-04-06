"""Graph-level type compatibility validation for primitives."""

from __future__ import annotations

from agent_foundry.primitives.errors import InvalidPromptKeyError, TypeMismatchError
from agent_foundry.primitives.models import (
    Conditional,
    GateAction,
    Loop,
    Primitive,
    Retry,
    Sequence,
    get_type_args,
)


def validate_primitive(prim: Primitive) -> None:
    """Recursively validate type compatibility across a primitive tree.

    Raises TypeMismatchError or InvalidPromptKeyError on the first
    incompatibility found.
    """
    if isinstance(prim, Sequence):
        _validate_sequence(prim)
    elif isinstance(prim, Loop):
        _validate_loop(prim)
    elif isinstance(prim, Retry):
        _validate_retry(prim)
    elif isinstance(prim, Conditional):
        _validate_conditional(prim)
    elif isinstance(prim, GateAction):
        _validate_gate_action(prim)


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


def _validate_sequence(seq: Sequence) -> None:
    seq_in, seq_out = get_type_args(seq)
    step_types = [get_type_args(s) for s in seq.steps]

    # Accumulated state starts with Sequence input fields
    accumulated_fields = set(seq_in.model_fields.keys())

    for i, (step_in, step_out) in enumerate(step_types):
        # Step input fields must be available in accumulated state
        _fields_available(step_in, accumulated_fields, f"Sequence step {i} input")
        # Step output fields merge into accumulated state
        accumulated_fields |= set(step_out.model_fields.keys())

    # Sequence output fields must be available in final accumulated state
    _fields_available(seq_out, accumulated_fields, "Sequence output")

    # Recurse into each step
    for step in seq.steps:
        validate_primitive(step)


def _validate_loop(loop: Loop) -> None:
    # Loop body type compatibility is deferred to the compiler (CS3).
    # The body's input type may differ from the loop's input type due to
    # item_key injection and parent context joining. Only recurse into
    # the body to catch errors within it.
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

    # Re-entry: body output feeds back as body input on next attempt
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
        # No else branch: this is a "detour" — state type must be stable.
        # All four types must be identical: Conditional.I == Conditional.O
        # == then.I == then.O
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
        # Both branches present: standard boundary checks.
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
