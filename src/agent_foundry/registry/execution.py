"""Role execution with quality controls."""

import concurrent.futures
from collections.abc import Callable
from typing import Any

from agent_foundry.registry.errors import RoleExecutionError
from agent_foundry.registry.spec import RoleSpec

FF_RETRY_TIMEOUTS = False


def execute_role(
    spec: RoleSpec,
    inputs: dict[str, Any],
    handler: Callable,
    node_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a role handler with optional quality controls.

    Args:
        spec: The role specification.
        inputs: The input data to pass to the handler.
        handler: The callable that performs the role logic.
        node_config: Static per-node configuration.

    Returns:
        The handler's output dict.

    Raises:
        RoleExecutionError: If timeout or retry exhaustion fails.
    """
    if node_config is None:
        node_config = {}

    if FF_RETRY_TIMEOUTS:
        return _execute_with_quality_controls(spec, inputs, handler, node_config)
    return handler(inputs, node_config)


def _execute_with_quality_controls(
    spec: RoleSpec,
    inputs: dict[str, Any],
    handler: Callable,
    node_config: dict[str, Any],
) -> dict[str, Any]:
    max_attempts = 1 + spec.quality_controls.max_retries
    timeout = spec.quality_controls.timeout_seconds
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return _execute_with_timeout(handler, inputs, node_config, timeout, spec.name)
        except RoleExecutionError:
            raise
        except Exception as e:
            last_error = e
            if attempt < max_attempts - 1:
                continue

    raise RoleExecutionError(
        message=(f"Role '{spec.name}' failed after {max_attempts} attempts: {last_error}"),
        role_name=spec.name,
        phase="retry_exhausted",
    )


def _execute_with_timeout(
    handler: Callable,
    inputs: dict[str, Any],
    node_config: dict[str, Any],
    timeout: int,
    role_name: str,
) -> dict[str, Any]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(handler, inputs, node_config)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as err:
            raise RoleExecutionError(
                message=f"Role '{role_name}' timed out after {timeout}s",
                role_name=role_name,
                phase="timeout",
            ) from err
