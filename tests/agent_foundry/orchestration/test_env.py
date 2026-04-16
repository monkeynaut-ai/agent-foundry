from __future__ import annotations

from unittest.mock import MagicMock

from agent_foundry.orchestration.env import build_container_env


def test_build_container_env_includes_required_keys() -> None:
    primitive = MagicMock()
    env = build_container_env(
        primitive,
        oauth_token="tok-abc",
        role_instructions_path="/home/claude/role-instructions.md",
    )
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-abc"
    assert env["ACP_ROLE_INSTRUCTIONS_PATH"] == "/home/claude/role-instructions.md"


def test_build_container_env_merges_extra() -> None:
    primitive = MagicMock()
    env = build_container_env(
        primitive,
        oauth_token="t",
        role_instructions_path="/r",
        extra={"FOO": "bar", "BAZ": "1"},
    )
    assert env["FOO"] == "bar"
    assert env["BAZ"] == "1"


def test_extra_cannot_silently_override_required_keys() -> None:
    primitive = MagicMock()
    env = build_container_env(
        primitive,
        oauth_token="real",
        role_instructions_path="/r",
        extra={"CLAUDE_CODE_OAUTH_TOKEN": "fake"},
    )
    # Required keys win over extra.
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "real"
