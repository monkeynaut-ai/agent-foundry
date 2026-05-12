"""MCP server configuration models."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


class MCPTransportKind(StrEnum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable-http"


class StdioTransport(BaseModel):
    kind: Literal[MCPTransportKind.STDIO] = MCPTransportKind.STDIO
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("command")
    @classmethod
    def command_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("command must not be empty")
        return v


class StreamableHttpTransport(BaseModel):
    kind: Literal[MCPTransportKind.STREAMABLE_HTTP] = MCPTransportKind.STREAMABLE_HTTP
    url: str
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def url_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("url must not be empty")
        return v


MCPTransport = Annotated[
    StdioTransport | StreamableHttpTransport,
    Field(discriminator="kind"),
]


class MCPServerConfig(BaseModel):
    name: str
    transport: MCPTransport
    required_env_keys: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("name must not be empty")
        return v
