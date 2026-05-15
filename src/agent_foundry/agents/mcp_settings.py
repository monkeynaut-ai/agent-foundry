"""MCP settings builder for Claude Code configuration files.

Claude Code stores MCP server configuration in two places:
  - /home/claude/.claude.json  — server definitions, keyed by project directory
  - /home/claude/.claude/settings.json — tool permissions (allow list)
"""

from __future__ import annotations

from typing import Any

from agent_foundry.primitives.mcp import McpServer, McpTransport


def build_mcp_permissions(servers: dict[str, McpServer]) -> dict[str, Any]:
    """Build the permissions patch for settings.json."""
    return {
        "permissions": {"allow": [f"mcp__{name}__*" for name in servers]},
    }


def build_claude_json_project_entry(servers: dict[str, McpServer]) -> dict[str, Any]:
    """Build the project entry for .claude.json mcpServers.

    Claude Code reads MCP server definitions from
    ``projects[<project_dir>]["mcpServers"]`` in ``~/.claude.json``.
    """
    return {
        "allowedTools": [],
        "mcpContextUris": [],
        "mcpServers": {name: _serialize_server_claude_json(cfg) for name, cfg in servers.items()},
        "enabledMcpjsonServers": [],
        "disabledMcpjsonServers": [],
        "hasTrustDialogAccepted": True,
    }


def _serialize_server_claude_json(cfg: McpServer) -> dict[str, Any]:
    if cfg.kind == McpTransport.STDIO:
        return {"type": "stdio", "command": cfg.command, "args": cfg.args, "env": cfg.env}
    return {"type": "http", "url": cfg.url, "headers": cfg.headers}
