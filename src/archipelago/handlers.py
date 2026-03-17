"""Archipelago handler registry."""

from typing import Any

from archipelago.docker_worker.handler import docker_worker_handler


def spec_approval_gate_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Auto-approve gate for automated runs."""
    return {**state, "approved": True, "approver": "auto"}


ARCHIPELAGO_HANDLERS: dict[str, Any] = {
    "coding_implement_feature_from_spec": docker_worker_handler,
    "write_unit_tests_from_spec": docker_worker_handler,
    "code_implement_from_tests": docker_worker_handler,
}
