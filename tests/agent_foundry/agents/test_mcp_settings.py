"""Tests for MCP settings builder."""

from agent_foundry.agents.mcp_settings import build_claude_json_project_entry, build_mcp_permissions
from agent_foundry.primitives.mcp import StdioMcpServer, StreamableHttpMcpServer


class TestBuildMcpSettings:
    def test_stdio_server_produces_permissions(self):
        result = build_mcp_permissions(
            {"fs": StdioMcpServer(command="npx", args=["-y", "mcp-fs"], env={"HOME": "/tmp"})}
        )
        assert result == {"permissions": {"allow": ["mcp__fs__*"]}}

    def test_http_server_produces_permissions(self):
        result = build_mcp_permissions(
            {
                "svc": StreamableHttpMcpServer(
                    url="http://localhost:9000/mcp", headers={"X-Api-Key": "secret"}
                )
            }
        )
        assert result == {"permissions": {"allow": ["mcp__svc__*"]}}

    def test_mixed_servers_produces_permissions_for_both(self):
        result = build_mcp_permissions(
            {
                "fs": StdioMcpServer(command="npx"),
                "api": StreamableHttpMcpServer(url="http://localhost:8080/mcp"),
            }
        )
        assert "mcp__fs__*" in result["permissions"]["allow"]
        assert "mcp__api__*" in result["permissions"]["allow"]

    def test_empty_dict_produces_empty_allow_list(self):
        result = build_mcp_permissions({})
        assert result == {"permissions": {"allow": []}}

    def test_permissions_generated_for_each_server(self):
        result = build_mcp_permissions(
            {
                "a": StdioMcpServer(command="cmd-a"),
                "b": StdioMcpServer(command="cmd-b"),
                "c": StreamableHttpMcpServer(url="http://localhost/c"),
            }
        )
        assert len(result["permissions"]["allow"]) == 3

    def test_no_mcp_servers_key_in_output(self):
        result = build_mcp_permissions({"srv": StdioMcpServer(command="npx")})
        assert "mcpServers" not in result


class TestBuildClaudeJsonProjectEntry:
    def test_stdio_server_serialized_with_type_field(self):
        result = build_claude_json_project_entry(
            {"fs": StdioMcpServer(command="npx", args=["-y", "mcp-fs"], env={"HOME": "/tmp"})}
        )
        assert result["mcpServers"] == {
            "fs": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "mcp-fs"],
                "env": {"HOME": "/tmp"},
            }
        }

    def test_http_server_serialized_with_type_field(self):
        result = build_claude_json_project_entry(
            {
                "svc": StreamableHttpMcpServer(
                    url="http://localhost:9000/mcp", headers={"X-Api-Key": "secret"}
                )
            }
        )
        assert result["mcpServers"] == {
            "svc": {
                "type": "http",
                "url": "http://localhost:9000/mcp",
                "headers": {"X-Api-Key": "secret"},
            }
        }

    def test_required_claude_json_fields_present(self):
        result = build_claude_json_project_entry({"s": StdioMcpServer(command="cmd")})
        assert result["hasTrustDialogAccepted"] is True
        assert result["allowedTools"] == []
        assert result["mcpContextUris"] == []
        assert result["enabledMcpjsonServers"] == []
        assert result["disabledMcpjsonServers"] == []

    def test_stdio_defaults_serialized(self):
        result = build_claude_json_project_entry({"srv": StdioMcpServer(command="npx")})
        assert result["mcpServers"]["srv"] == {
            "type": "stdio",
            "command": "npx",
            "args": [],
            "env": {},
        }
