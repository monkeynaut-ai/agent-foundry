"""Configuration for Agent Foundry's eval API server.

Reads ``agent_foundry.config`` (TOML) from the application's working
directory. The config declares where to find the application's
:class:`AICallRegistry` and how to bind the HTTP server.

Schema::

    registry = "module.path:VARIABLE"

    [api]
    host = "127.0.0.1"
    port = 8000

The ``registry`` value is a ``module.path:attribute`` string that the
registry loader resolves at startup; this module does not import it.
The ``[api]`` table is optional and uses sensible defaults if omitted.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CONFIG_FILENAME = "agent_foundry.config"


class ConfigNotFoundError(FileNotFoundError):
    """Raised when the expected config file is not present on disk."""


class ApiBindingConfig(BaseModel):
    """HTTP binding for the API server."""

    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)


class EvalApiConfig(BaseModel):
    """Parsed contents of ``agent_foundry.config``."""

    model_config = ConfigDict(extra="forbid")

    registry: str = Field(min_length=1)
    api: ApiBindingConfig = Field(default_factory=ApiBindingConfig)


def load_config(path: Path | None = None) -> EvalApiConfig:
    """Load :class:`EvalApiConfig` from ``path`` or ``CWD/agent_foundry.config``.

    Raises :class:`ConfigNotFoundError` if the file is absent,
    :class:`tomllib.TOMLDecodeError` if it is malformed TOML, and
    :class:`pydantic.ValidationError` if its structure is invalid.
    """
    resolved = path if path is not None else Path.cwd() / DEFAULT_CONFIG_FILENAME

    if not resolved.is_file():
        raise ConfigNotFoundError(f"Eval API config not found: {resolved}")

    with resolved.open("rb") as fh:
        data = tomllib.load(fh)

    return EvalApiConfig.model_validate(data)
