"""Tests for RoleStack model."""

from agent_foundry.acp.protocol import MarkerMapping
from agent_foundry.acp.role_stack import RoleStack


class TestRoleStack:
    def test_given_empty_stack_when_constructed_then_all_defaults_empty(self):
        stack = RoleStack()
        assert stack.claude_md is None
        assert stack.skills == {}
        assert stack.marker_mappings == []
        assert stack.settings == {}
        assert stack.plugins == []
        assert stack.env_allowlist_extra == set()
        assert stack.extra_env == {}

    def test_given_full_stack_when_constructed_then_all_fields_stored(self):
        mappings = [
            MarkerMapping(pattern=r"^DONE$", event_type="task_complete"),
        ]
        stack = RoleStack(
            claude_md="You are a code reviewer.",
            skills={"review": "Review code and suggest improvements."},
            marker_mappings=mappings,
            settings={"permissions": {"allow": ["Read"]}},
            plugins=["pyright-lsp"],
            env_allowlist_extra={"CUSTOM_VAR"},
            extra_env={"MODE": "review"},
        )
        assert stack.claude_md == "You are a code reviewer."
        assert "review" in stack.skills
        assert len(stack.marker_mappings) == 1
        assert stack.marker_mappings[0].event_type == "task_complete"
        assert stack.plugins == ["pyright-lsp"]
        assert "CUSTOM_VAR" in stack.env_allowlist_extra
        assert stack.extra_env["MODE"] == "review"

    def test_given_stack_when_serialized_then_round_trips(self):
        stack = RoleStack(
            claude_md="instructions",
            marker_mappings=[
                MarkerMapping(
                    pattern=r"^HELP\s+(\{.*\})$",
                    event_type="clarification_requested",
                    payload_group=1,
                ),
            ],
        )
        data = stack.model_dump()
        restored = RoleStack.model_validate(data)
        assert restored.claude_md == stack.claude_md
        assert len(restored.marker_mappings) == 1
        assert restored.marker_mappings[0].payload_group == 1
