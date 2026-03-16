"""ApprovalGateHandler — unit tests for deterministic approval gate handler."""

from pathlib import Path

from agent_foundry.registry.spec import load_role_spec
from archipelago.agents.approval_gate import ApprovalGateHandler

FRAMEWORK_CAPS_DIR = Path(__file__).parent.parent.parent / "src" / "agent_foundry" / "roles"


def _make_spec():
    return load_role_spec(FRAMEWORK_CAPS_DIR / "human_approval_gate.yaml")


def _make_state():
    return {
        "feature_spec": {
            "title": "Task Manager MVP",
            "objective": "Implement core task management",
            "acceptance_criteria": ["CRUD operations work", "API responds under 200ms"],
            "pr_slices": [{"title": "Core API", "commits": ["Add endpoints"]}],
        },
        "test_plan": {
            "feature_name": "Task Manager Core",
            "test_cases": [{"name": "test_create_task", "type": "unit"}],
            "coverage_targets": ["task_service"],
        },
    }


class TestApprovalGateHandler:
    def test_given_state_when_called_then_returns_approved_true(self):
        handler = ApprovalGateHandler(_make_spec())
        result = handler(_make_state())
        assert result["approved"] is True

    def test_given_state_when_called_then_returns_approver_auto(self):
        handler = ApprovalGateHandler(_make_spec())
        result = handler(_make_state())
        assert result["approver"] == "auto"

    def test_given_state_when_called_then_preserves_existing_state(self):
        handler = ApprovalGateHandler(_make_spec())
        state = _make_state()
        result = handler(state)
        assert result["feature_spec"] == state["feature_spec"]
        assert result["test_plan"] == state["test_plan"]
