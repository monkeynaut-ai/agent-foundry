"""MCP server configuration types for AgentAction declarations."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, BaseModel, Field, TypeAdapter
from pydantic.functional_validators import AfterValidator

_http_url_adapter: TypeAdapter[AnyHttpUrl] = TypeAdapter(AnyHttpUrl)


def _validate_http_url(v: str) -> str:
    _http_url_adapter.validate_python(v)
    return v


HttpUrl = Annotated[str, AfterValidator(_validate_http_url)]


class McpTransport(StrEnum):
    """Transport mechanism for an MCP server connection."""

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


class StdioMcpServer(BaseModel):
    """MCP server spawned as a local subprocess."""

    kind: Literal[McpTransport.STDIO] = McpTransport.STDIO
    command: str = Field(min_length=1, description="Executable to spawn as the MCP server process.")
    args: list[str] = Field(
        default_factory=list,
        description=(
            "Command-line arguments passed to the server process."
            ' Example: ["-y", "mcp-server-filesystem", "/workspace"]'
        ),
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Additional environment variables merged into the server process environment.",
    )


class StreamableHttpMcpServer(BaseModel):
    """MCP server accessed over HTTP using the Streamable HTTP transport."""

    kind: Literal[McpTransport.STREAMABLE_HTTP] = McpTransport.STREAMABLE_HTTP
    url: HttpUrl = Field(description="HTTP or HTTPS endpoint URL for the MCP server.")
    headers: dict[str, str] = Field(default_factory=dict)


McpServer = Annotated[
    StdioMcpServer | StreamableHttpMcpServer,
    Field(discriminator="kind"),
]
