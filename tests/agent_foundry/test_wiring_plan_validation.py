"""S3.2 — Structural validation errors (missing required fields).

Tests: missing required fields yield clear error messages with JSON paths.
"""

import pytest
from pydantic import ValidationError

from agent_foundry.planner.wiring_plan import GraphWiringPlan


class TestMissingRequiredFields:
    """Missing required fields produce clear validation errors."""

    def test_missing_nodes_raises_error(self):
        with pytest.raises(ValidationError) as exc_info:
            GraphWiringPlan(goal="test", edges=[], entry_point="a", role_versions={})
        errors = exc_info.value.errors()
        field_names = [e["loc"][0] for e in errors]
        assert "nodes" in field_names

    def test_missing_goal_raises_error(self):
        with pytest.raises(ValidationError) as exc_info:
            GraphWiringPlan(
                nodes=[{"id": "a", "role": "test"}],
                edges=[],
                entry_point="a",
                role_versions={},
            )
        errors = exc_info.value.errors()
        field_names = [e["loc"][0] for e in errors]
        assert "goal" in field_names

    def test_missing_entry_point_raises_error(self):
        with pytest.raises(ValidationError) as exc_info:
            GraphWiringPlan(
                goal="test",
                nodes=[{"id": "a", "role": "test"}],
                edges=[],
                role_versions={},
            )
        errors = exc_info.value.errors()
        field_names = [e["loc"][0] for e in errors]
        assert "entry_point" in field_names

    def test_error_message_includes_field_path(self):
        with pytest.raises(ValidationError) as exc_info:
            GraphWiringPlan(goal="test", edges=[], entry_point="a", role_versions={})
        msg = str(exc_info.value)
        assert "nodes" in msg

    def test_missing_node_id_raises_error(self):
        with pytest.raises(ValidationError):
            GraphWiringPlan(
                goal="test",
                nodes=[{"role": "test"}],
                edges=[],
                entry_point="a",
                role_versions={},
            )

    def test_missing_node_role_raises_error(self):
        with pytest.raises(ValidationError):
            GraphWiringPlan(
                goal="test",
                nodes=[{"id": "a"}],
                edges=[],
                entry_point="a",
                role_versions={},
            )
