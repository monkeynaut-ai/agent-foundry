"""Role execution tests.

Tests: valid input returns output; quality controls (timeout, retry).
"""

from typing import Any

from agent_foundry.registry.execution import execute_role
from agent_foundry.registry.spec import (
    ImplementationPointer,
    QualityControls,
    RoleSpec,
)


def _make_spec() -> RoleSpec:
    return RoleSpec(
        name="test_cap",
        description="A test role",
        version="1.0.0",
        implementation=ImplementationPointer(module="builtins", class_name="dict"),
        tags=[],
        quality_controls=QualityControls(),
    )


def _echo_handler(
    inputs: dict[str, Any], node_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Simple handler that wraps input query into result."""
    return {"result": inputs.get("query", "")}


class TestValidExecution:
    """Valid inputs produce valid outputs."""

    def test_valid_input_returns_output(self):
        spec = _make_spec()
        result = execute_role(spec, {"query": "hello"}, _echo_handler)
        assert result == {"result": "hello"}

    def test_output_matches_handler_return(self):
        spec = _make_spec()
        result = execute_role(spec, {"query": "test"}, _echo_handler)
        assert result["result"] == "test"
