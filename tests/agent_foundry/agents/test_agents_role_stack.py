"""Tests for RoleStack model."""

from agent_foundry.agents.role_stack import RoleStack


class TestRoleStack:
    def test_given_empty_stack_when_constructed_then_all_defaults_empty(self):
        stack = RoleStack()
        assert stack.claude_md is None
        assert stack.skills == {}
        assert stack.settings == {}
        assert stack.plugins == []
        assert stack.env_allowlist_extra == set()
        assert stack.extra_env == {}

    def test_given_full_stack_when_constructed_then_all_fields_stored(self):
        stack = RoleStack(
            claude_md="You are a code reviewer.",
            skills={"review": "Review code and suggest improvements."},
            settings={"permissions": {"allow": ["Read"]}},
            plugins=["pyright-lsp"],
            env_allowlist_extra={"CUSTOM_VAR"},
            extra_env={"MODE": "review"},
        )
        assert stack.claude_md == "You are a code reviewer."
        assert "review" in stack.skills
        assert stack.plugins == ["pyright-lsp"]
        assert "CUSTOM_VAR" in stack.env_allowlist_extra
        assert stack.extra_env["MODE"] == "review"

    def test_given_stack_when_serialized_then_round_trips(self):
        stack = RoleStack(
            claude_md="instructions",
            skills={"s": "content"},
            plugins=["p"],
        )
        data = stack.model_dump()
        restored = RoleStack.model_validate(data)
        assert restored.claude_md == stack.claude_md
        assert restored.skills == stack.skills
        assert restored.plugins == stack.plugins
