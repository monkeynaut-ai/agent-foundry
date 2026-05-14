"""Tests for MCP settings builder."""

from agent_foundry.agents.mcp_settings import build_mcp_settings
from agent_foundry.primitives.mcp import StdioMcpServer, StreamableHttpMcpServer


class TestBuildMcpSettings:
    def test_stdio_server_produces_correct_shape(self):
        result = build_mcp_settings(
            {"fs": StdioMcpServer(command="npx", args=["-y", "mcp-fs"], env={"HOME": "/tmp"})}
        )
        assert result == {
            "mcpServers": {
                "fs": {"command": "npx", "args": ["-y", "mcp-fs"], "env": {"HOME": "/tmp"}}
            },
            "permissions": {"allow": ["mcp__fs__*"]},
        }

    def test_http_server_produces_correct_shape(self):
        result = build_mcp_settings(
            {
                "svc": StreamableHttpMcpServer(
                    url="http://localhost:9000/mcp", headers={"X-Api-Key": "secret"}
                )
            }
        )
        assert result == {
            "mcpServers": {
                "svc": {
                    "url": "http://localhost:9000/mcp",
                    "headers": {"X-Api-Key": "secret"},
                }
            },
            "permissions": {"allow": ["mcp__svc__*"]},
        }

    def test_mixed_servers_produces_entries_for_both(self):
        result = build_mcp_settings(
            {
                "fs": StdioMcpServer(command="npx"),
                "api": StreamableHttpMcpServer(url="http://localhost:8080/mcp"),
            }
        )
        assert "fs" in result["mcpServers"]
        assert "api" in result["mcpServers"]
        assert "mcp__fs__*" in result["permissions"]["allow"]
        assert "mcp__api__*" in result["permissions"]["allow"]

    def test_empty_dict_produces_empty_mcp_servers(self):
        result = build_mcp_settings({})
        assert result == {"mcpServers": {}, "permissions": {"allow": []}}

    def test_permissions_generated_for_each_server(self):
        result = build_mcp_settings(
            {
                "a": StdioMcpServer(command="cmd-a"),
                "b": StdioMcpServer(command="cmd-b"),
                "c": StreamableHttpMcpServer(url="http://localhost/c"),
            }
        )
        assert len(result["permissions"]["allow"]) == 3

    def test_stdio_env_vars_preserved(self):
        env = {"KEY1": "val1", "KEY2": "val2", "KEY3": "val3"}
        result = build_mcp_settings({"srv": StdioMcpServer(command="cmd", env=env)})
        assert result["mcpServers"]["srv"]["env"] == env

    def test_http_headers_preserved(self):
        headers = {
            "Authorization": "Bearer tok",
            "X-Trace": "abc",
            "Content-Type": "application/json",
        }
        result = build_mcp_settings(
            {"srv": StreamableHttpMcpServer(url="http://example.com/mcp", headers=headers)}
        )
        assert result["mcpServers"]["srv"]["headers"] == headers

    def test_stdio_defaults_serialized(self):
        result = build_mcp_settings({"srv": StdioMcpServer(command="npx")})
        assert result["mcpServers"]["srv"] == {"command": "npx", "args": [], "env": {}}
