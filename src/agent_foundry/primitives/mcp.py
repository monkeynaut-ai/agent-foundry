"""MCP server configuration types for AgentAction declarations."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class McpTransport(StrEnum):
    """Transport mechanism for an MCP server connection.

    Code branches on this value to select the Claude Code serialization path.
    """

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


class StdioMcpServer(BaseModel):
    """MCP server spawned as a local subprocess."""

    kind: Literal[McpTransport.STDIO] = McpTransport.STDIO
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class StreamableHttpMcpServer(BaseModel):
    """MCP server accessed over HTTP using the Streamable HTTP transport."""

    kind: Literal[McpTransport.STREAMABLE_HTTP] = McpTransport.STREAMABLE_HTTP
    url: str = Field(min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)


McpServer = Annotated[
    StdioMcpServer | StreamableHttpMcpServer,
    Field(discriminator="kind"),
]
