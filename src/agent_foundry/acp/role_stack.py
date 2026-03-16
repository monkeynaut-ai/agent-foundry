"""Role stack definition for containerized AI agents.

A role stack defines the customizations applied to a container
before the agent starts: instructions, tools, permissions, markers, etc.
Products provide role stacks; Agent Foundry applies them.
"""

from typing import Any

from pydantic import BaseModel

from agent_foundry.acp.protocol import MarkerMapping


class RoleStack(BaseModel):
    """Defines what customizations a container gets before the agent starts.

    Attributes:
        claude_md: Content for the CLAUDE.md file (agent instructions).
        skills: Mapping of skill name to SKILL.md content.
        marker_mappings: Product-defined marker-to-ACP-event translations.
        settings: Claude Code settings.json overrides.
        plugins: Plugin install commands to run at container start.
        env_allowlist_extra: Additional env vars to forward into the container.
        extra_env: Static env vars to inject into the container.
    """

    claude_md: str | None = None
    skills: dict[str, str] = {}
    marker_mappings: list[MarkerMapping] = []
    settings: dict[str, Any] = {}
    plugins: list[str] = []
    env_allowlist_extra: set[str] = set()
    extra_env: dict[str, str] = {}
