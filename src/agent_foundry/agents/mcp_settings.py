"""MCP settings builder for Claude Code settings.local.json."""

from __future__ import annotations

from typing import Any

from agent_foundry.primitives.mcp import McpServer, McpTransport


def build_mcp_settings(servers: dict[str, McpServer]) -> dict[str, Any]:
    """Convert platform MCP server declarations into Claude Code settings format."""
    return {
        "mcpServers": {name: _serialize_server(cfg) for name, cfg in servers.items()},
        "permissions": {"allow": [f"mcp__{name}__*" for name in servers]},
    }


def _serialize_server(cfg: McpServer) -> dict[str, Any]:
    if cfg.kind == McpTransport.STDIO:
        return {"command": cfg.command, "args": cfg.args, "env": cfg.env}
    return {"url": cfg.url, "headers": cfg.headers}
