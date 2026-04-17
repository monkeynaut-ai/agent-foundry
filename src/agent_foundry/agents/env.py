"""Agent Container environment variable builders for container lockdown.

Pure functions that convert lockdown configuration into Docker container
environment variables. Reusable by any product built on Agent Foundry.
"""


def build_lockdown_env(
    hidden_dirs: list[str] | None = None,
    readonly_dirs: list[str] | None = None,
    role_instructions_path: str | None = None,
) -> dict[str, str]:
    """Build lockdown environment variables for Agent Container containers.

    These env vars are read by lockdown.sh inside the container to apply
    filesystem restrictions before the agent process starts.

    Args:
        hidden_dirs: Paths to make completely inaccessible (chmod 000).
        readonly_dirs: Paths to make read-only (chmod -R a-w).
        role_instructions_path: Path to role-specific CLAUDE.md to append.

    Returns:
        Dict of env var name → value. Empty dict if no lockdown configured.
    """
    env: dict[str, str] = {}
    if hidden_dirs:
        env["WORKSPACE_HIDDEN_DIRS"] = ",".join(hidden_dirs)
    if readonly_dirs:
        env["WORKSPACE_READONLY_DIRS"] = ",".join(readonly_dirs)
    if role_instructions_path:
        env["AGENT_ROLE_INSTRUCTIONS_PATH"] = role_instructions_path
    return env
