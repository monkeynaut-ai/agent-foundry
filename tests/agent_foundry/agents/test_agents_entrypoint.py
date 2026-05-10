"""Tests for base entrypoint and lockdown script structure.

Validates that the entrypoint script sources the lockdown script,
contains the required sections in the correct order, and that the
lockdown script handles filesystem restrictions properly.
"""

from pathlib import Path

_DOCKER_DIR = Path(__file__).resolve().parents[3] / "src/agent_foundry/agents/docker"
ENTRYPOINT = _DOCKER_DIR / "entrypoint.sh"
LOCKDOWN = _DOCKER_DIR / "lockdown.sh"


def _read_entrypoint() -> str:
    return ENTRYPOINT.read_text()


def _read_lockdown() -> str:
    return LOCKDOWN.read_text()


class TestFilesystemLockdown:
    def test_given_entrypoint_when_read_then_sources_lockdown_script(self):
        content = _read_entrypoint()
        assert ". /home/claude/lockdown.sh" in content

    def test_given_entrypoint_when_read_then_lockdown_after_repo_clone(self):
        content = _read_entrypoint()
        clone_pos = content.index("Repo clone")
        lockdown_pos = content.index("Filesystem lockdown")
        assert lockdown_pos > clone_pos

    def test_given_entrypoint_when_read_then_lockdown_before_role_instructions(self):
        content = _read_entrypoint()
        lockdown_pos = content.index("Filesystem lockdown")
        role_pos = content.index("Role-specific instructions")
        assert lockdown_pos < role_pos


class TestLockdownScript:
    def test_given_lockdown_script_when_read_then_handles_hidden_dirs(self):
        content = _read_lockdown()
        assert "WORKSPACE_HIDDEN_DIRS" in content
        assert "chmod 000" in content

    def test_given_lockdown_script_when_read_then_handles_readonly_dirs(self):
        content = _read_lockdown()
        assert "WORKSPACE_READONLY_DIRS" in content
        assert "chmod -R a-w" in content

    def test_given_lockdown_script_when_read_then_guards_nonexistent_dirs(self):
        content = _read_lockdown()
        assert '[ -d "$dir" ]' in content


class TestRoleInstructions:
    def test_given_entrypoint_when_read_then_contains_role_instructions_handling(self):
        content = _read_entrypoint()
        assert "AGENT_ROLE_INSTRUCTIONS_PATH" in content

    def test_given_entrypoint_when_read_then_appends_rather_than_overwrites(self):
        content = _read_entrypoint()
        assert ">> /home/claude/.claude/CLAUDE.md" in content


class TestGosuUserDrop:
    def test_given_entrypoint_when_read_then_interactive_fallback_uses_gosu(self):
        content = _read_entrypoint()
        assert "exec gosu claude /home/claude/.local/bin/claude" in content

    def test_given_entrypoint_when_read_then_git_clone_uses_gosu(self):
        content = _read_entrypoint()
        assert "gosu claude git clone" in content
