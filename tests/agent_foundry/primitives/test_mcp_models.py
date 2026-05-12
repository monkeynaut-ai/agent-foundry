"""Unit tests for MCP server configuration models."""

import pytest
from pydantic import ValidationError

from agent_foundry.primitives.mcp import (
    MCPServerConfig,
    MCPTransportKind,
    StdioTransport,
    StreamableHttpTransport,
)


class TestMCPTransportKind:
    def test_stdio_string_value(self):
        assert MCPTransportKind.STDIO == "stdio"

    def test_streamable_http_string_value(self):
        assert MCPTransportKind.STREAMABLE_HTTP == "streamable-http"

    def test_is_str_enum(self):
        from enum import StrEnum

        assert issubclass(MCPTransportKind, StrEnum)


class TestStdioTransport:
    def test_constructs_with_command(self):
        transport = StdioTransport(command="npx")
        assert transport.command == "npx"

    def test_kind_fixed_to_stdio(self):
        transport = StdioTransport(command="npx")
        assert transport.kind == MCPTransportKind.STDIO

    def test_args_defaults_to_empty_list(self):
        transport = StdioTransport(command="npx")
        assert transport.args == []

    def test_env_defaults_to_empty_dict(self):
        transport = StdioTransport(command="npx")
        assert transport.env == {}

    def test_rejects_empty_command(self):
        with pytest.raises(ValidationError):
            StdioTransport(command="")

    def test_accepts_args_and_env(self):
        transport = StdioTransport(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={"GITHUB_TOKEN": "token"},
        )
        assert transport.args == ["-y", "@modelcontextprotocol/server-github"]
        assert transport.env == {"GITHUB_TOKEN": "token"}


class TestStreamableHttpTransport:
    def test_constructs_with_url(self):
        transport = StreamableHttpTransport(url="https://example.com/mcp")
        assert transport.url == "https://example.com/mcp"

    def test_kind_fixed_to_streamable_http(self):
        transport = StreamableHttpTransport(url="https://example.com/mcp")
        assert transport.kind == MCPTransportKind.STREAMABLE_HTTP

    def test_headers_defaults_to_empty_dict(self):
        transport = StreamableHttpTransport(url="https://example.com/mcp")
        assert transport.headers == {}

    def test_rejects_empty_url(self):
        with pytest.raises(ValidationError):
            StreamableHttpTransport(url="")

    def test_accepts_headers(self):
        transport = StreamableHttpTransport(
            url="https://example.com/mcp",
            headers={"Authorization": "Bearer tok"},
        )
        assert transport.headers == {"Authorization": "Bearer tok"}


class TestMCPServerConfig:
    def test_constructs_with_stdio_transport(self):
        config = MCPServerConfig(name="github", transport=StdioTransport(command="npx"))
        assert config.name == "github"
        assert isinstance(config.transport, StdioTransport)

    def test_constructs_with_streamable_http_transport(self):
        config = MCPServerConfig(
            name="remote-mcp",
            transport=StreamableHttpTransport(url="https://example.com/mcp"),
        )
        assert config.name == "remote-mcp"
        assert isinstance(config.transport, StreamableHttpTransport)

    def test_rejects_empty_name(self):
        with pytest.raises(ValidationError):
            MCPServerConfig(name="", transport=StdioTransport(command="npx"))

    def test_required_env_keys_defaults_to_empty_list(self):
        config = MCPServerConfig(name="srv", transport=StdioTransport(command="npx"))
        assert config.required_env_keys == []

    def test_required_env_keys_accepts_values(self):
        config = MCPServerConfig(
            name="srv",
            transport=StdioTransport(command="npx"),
            required_env_keys=["GITHUB_TOKEN", "GITHUB_ORG"],
        )
        assert config.required_env_keys == ["GITHUB_TOKEN", "GITHUB_ORG"]

    def test_discriminator_resolves_stdio_from_dict(self):
        config = MCPServerConfig(
            name="srv",
            transport={"kind": "stdio", "command": "npx", "args": ["-y", "server"]},
        )
        assert isinstance(config.transport, StdioTransport)
        assert config.transport.command == "npx"
        assert config.transport.args == ["-y", "server"]

    def test_discriminator_resolves_streamable_http_from_dict(self):
        config = MCPServerConfig(
            name="srv",
            transport={"kind": "streamable-http", "url": "https://example.com/mcp"},
        )
        assert isinstance(config.transport, StreamableHttpTransport)
        assert config.transport.url == "https://example.com/mcp"


class TestPublicAPIExports:
    def test_mcp_server_config_importable_from_primitives(self):
        from agent_foundry.primitives import MCPServerConfig as C

        assert C is MCPServerConfig

    def test_mcp_transport_kind_importable_from_primitives(self):
        from agent_foundry.primitives import MCPTransportKind as K

        assert K is MCPTransportKind

    def test_stdio_transport_importable_from_primitives(self):
        from agent_foundry.primitives import StdioTransport as S

        assert S is StdioTransport

    def test_streamable_http_transport_importable_from_primitives(self):
        from agent_foundry.primitives import StreamableHttpTransport as H

        assert H is StreamableHttpTransport
