"""Tests for MCP server configuration models."""

import pytest
from pydantic import TypeAdapter, ValidationError

from agent_foundry.primitives.mcp import (
    McpServer,
    McpTransport,
    StdioMcpServer,
    StreamableHttpMcpServer,
)


class TestMcpTransport:
    def test_transport_enum_members(self):
        assert set(McpTransport) == {McpTransport.STDIO, McpTransport.STREAMABLE_HTTP}

    def test_stdio_value(self):
        assert McpTransport.STDIO == "stdio"

    def test_streamable_http_value(self):
        assert McpTransport.STREAMABLE_HTTP == "streamable_http"

    def test_members_are_strings(self):
        for transport in McpTransport:
            assert isinstance(transport, str)


class TestStdioMcpServer:
    def test_stdio_server_construction_succeeds(self):
        server = StdioMcpServer(command="npx", args=["-y", "mcp-server"], env={"KEY": "val"})
        assert server.command == "npx"
        assert server.args == ["-y", "mcp-server"]
        assert server.env == {"KEY": "val"}
        assert server.kind == McpTransport.STDIO

    def test_stdio_defaults(self):
        server = StdioMcpServer(command="npx")
        assert server.args == []
        assert server.env == {}
        assert server.kind == McpTransport.STDIO

    def test_stdio_rejects_empty_command(self):
        with pytest.raises(ValidationError):
            StdioMcpServer(command="")

    def test_stdio_json_round_trip(self):
        server = StdioMcpServer(command="npx", args=["-y", "mcp-server"], env={"KEY": "val"})
        data = server.model_dump()
        reconstructed = StdioMcpServer.model_validate(data)
        assert reconstructed.command == server.command
        assert reconstructed.args == server.args
        assert reconstructed.env == server.env
        assert reconstructed.kind == server.kind


class TestStreamableHttpMcpServer:
    def test_http_server_construction_succeeds(self):
        server = StreamableHttpMcpServer(
            url="http://localhost:8080/mcp", headers={"Authorization": "Bearer tok"}
        )
        assert server.url == "http://localhost:8080/mcp"
        assert server.headers == {"Authorization": "Bearer tok"}
        assert server.kind == McpTransport.STREAMABLE_HTTP

    def test_http_defaults(self):
        server = StreamableHttpMcpServer(url="http://localhost:8080/mcp")
        assert server.headers == {}
        assert server.kind == McpTransport.STREAMABLE_HTTP

    def test_http_rejects_empty_url(self):
        with pytest.raises(ValidationError):
            StreamableHttpMcpServer(url="")

    def test_http_json_round_trip(self):
        server = StreamableHttpMcpServer(
            url="http://localhost:8080/mcp", headers={"Authorization": "Bearer tok"}
        )
        data = server.model_dump()
        reconstructed = StreamableHttpMcpServer.model_validate(data)
        assert reconstructed.url == server.url
        assert reconstructed.headers == server.headers
        assert reconstructed.kind == server.kind


class TestMcpServerUnion:
    def test_discriminated_union_resolves_stdio(self):
        adapter = TypeAdapter(McpServer)
        result = adapter.validate_python({"kind": "stdio", "command": "npx"})
        assert isinstance(result, StdioMcpServer)

    def test_discriminated_union_resolves_http(self):
        adapter = TypeAdapter(McpServer)
        result = adapter.validate_python(
            {"kind": "streamable_http", "url": "http://localhost:8080/mcp"}
        )
        assert isinstance(result, StreamableHttpMcpServer)
