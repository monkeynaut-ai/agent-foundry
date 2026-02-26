"""Capability execution with input/output schema enforcement."""

from collections.abc import Callable
from typing import Any

import jsonschema

from agent_foundry.registry.errors import CapabilityExecutionError
from agent_foundry.registry.spec import CapabilitySpec

FF_SCHEMA_ENFORCEMENT = True


def execute_capability(
    spec: CapabilitySpec,
    inputs: dict[str, Any],
    handler: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Execute a capability handler with optional schema enforcement.

    Args:
        spec: The capability specification with input/output schemas.
        inputs: The input data to pass to the handler.
        handler: The callable that performs the capability logic.

    Returns:
        The handler's output dict.

    Raises:
        CapabilityExecutionError: If input or output validation fails.
    """
    if FF_SCHEMA_ENFORCEMENT:
        _validate_schema(inputs, spec.inputs_schema, spec.name, "input_validation")

    result = handler(inputs)

    if FF_SCHEMA_ENFORCEMENT:
        _validate_schema(result, spec.outputs_schema, spec.name, "output_validation")

    return result


def _validate_schema(
    data: dict[str, Any],
    schema: dict[str, Any],
    capability_name: str,
    phase: str,
) -> None:
    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(data))
    if errors:
        field_paths = [
            ".".join(str(p) for p in err.absolute_path) or err.json_path
            for err in errors
        ]
        messages = [err.message for err in errors]
        raise CapabilityExecutionError(
            message=f"Schema {phase} failed for '{capability_name}': {'; '.join(messages)}",
            capability_name=capability_name,
            phase=phase,
            field_paths=field_paths,
        )
