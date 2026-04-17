"""Unit tests for ACP lockdown environment variable builder."""

from agent_foundry.agents.env import build_lockdown_env


class TestBuildLockdownEnv:
    def test_given_hidden_dirs_when_built_then_env_contains_comma_joined_acp_hidden_dirs(self):
        env = build_lockdown_env(hidden_dirs=["/workspace/src", "/workspace/.keys"])
        assert env["WORKSPACE_HIDDEN_DIRS"] == "/workspace/src,/workspace/.keys"

    def test_given_readonly_dirs_when_built_then_env_contains_comma_joined_acp_readonly_dirs(self):
        env = build_lockdown_env(readonly_dirs=["/workspace/tests", "/workspace/docs"])
        assert env["WORKSPACE_READONLY_DIRS"] == "/workspace/tests,/workspace/docs"

    def test_given_role_instructions_path_when_built_then_env_contains_acp_role_instructions_path(
        self,
    ):
        env = build_lockdown_env(role_instructions_path="/home/claude/.claude/CLAUDE-writer.md")
        assert env["ACP_ROLE_INSTRUCTIONS_PATH"] == "/home/claude/.claude/CLAUDE-writer.md"

    def test_given_no_dirs_when_built_then_env_is_empty(self):
        env = build_lockdown_env()
        assert env == {}

    def test_given_single_hidden_dir_when_built_then_no_trailing_comma(self):
        env = build_lockdown_env(hidden_dirs=["/workspace/src"])
        assert env["WORKSPACE_HIDDEN_DIRS"] == "/workspace/src"

    def test_given_all_fields_when_built_then_all_three_keys_present(self):
        env = build_lockdown_env(
            hidden_dirs=["/workspace/src"],
            readonly_dirs=["/workspace/tests"],
            role_instructions_path="/home/claude/.claude/CLAUDE.md",
        )
        assert "WORKSPACE_HIDDEN_DIRS" in env
        assert "WORKSPACE_READONLY_DIRS" in env
        assert "ACP_ROLE_INSTRUCTIONS_PATH" in env
