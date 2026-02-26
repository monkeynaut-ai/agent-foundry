"""Capability execution with input/output schema enforcement and quality controls."""

import concurrent.futures
from collections.abc import Callable
from typing import Any

import jsonschema

from agent_foundry.registry.errors import CapabilityExecutionError
from agent_foundry.registry.spec import CapabilitySpec

FF_SCHEMA_ENFORCEMENT = True
FF_RETRY_TIMEOUTS = False


def execute_capability(
    spec: CapabilitySpec,
    inputs: dict[str, Any],
    handler: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Execute a capability handler with optional schema enforcement and quality controls.

    Args:
        spec: The capability specification with input/output schemas.
        inputs: The input data to pass to the handler.
        handler: The callable that performs the capability logic.

    Returns:
        The handler's output dict.

    Raises:
        CapabilityExecutionError: If validation, timeout, or retry exhaustion fails.
    """
    if FF_SCHEMA_ENFORCEMENT:
        _validate_schema(inputs, spec.inputs_schema, spec.name, "input_validation")

    if FF_RETRY_TIMEOUTS:
        result = _execute_with_quality_controls(spec, inputs, handler)
    else:
        result = handler(inputs)

    if FF_SCHEMA_ENFORCEMENT:
        _validate_schema(result, spec.outputs_schema, spec.name, "output_validation")

    return result


def _execute_with_quality_controls(
    spec: CapabilitySpec,
    inputs: dict[str, Any],
    handler: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    max_attempts = 1 + spec.quality_controls.max_retries
    timeout = spec.quality_controls.timeout_seconds
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return _execute_with_timeout(handler, inputs, timeout, spec.name)
        except CapabilityExecutionError:
            raise
        except Exception as e:
            last_error = e
            if attempt < max_attempts - 1:
                continue

    raise CapabilityExecutionError(
        message=(
            f"Capability '{spec.name}' failed after {max_attempts} attempts: {last_error}"
        ),
        capability_name=spec.name,
        phase="retry_exhausted",
    )


def _execute_with_timeout(
    handler: Callable[[dict[str, Any]], dict[str, Any]],
    inputs: dict[str, Any],
    timeout: int,
    capability_name: str,
) -> dict[str, Any]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(handler, inputs)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise CapabilityExecutionError(
                message=f"Capability '{capability_name}' timed out after {timeout}s",
                capability_name=capability_name,
                phase="timeout",
            )


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
