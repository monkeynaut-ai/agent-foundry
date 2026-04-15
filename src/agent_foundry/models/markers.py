"""Annotated metadata markers for agent-foundry boundary models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

PLATFORM_DEFAULT_MAX_FILE_BYTES: Final[int] = 10_000_000


@dataclass(frozen=True)
class AgentFilePath:
    """Annotated metadata marker for fields that contain agent-written file paths.

    Attach via typing.Annotated:

        class ReviewerOutput(BaseModel):
            review_path: Annotated[str, AgentFilePath()]
            transcript_path: Annotated[str, AgentFilePath(max_size_bytes=50_000_000)]

    At runtime, the Plan 2 executor walks the JSON schema for fields
    carrying ``x-agent-file-path`` extensions and verifies the declared
    paths exist in the container and are within the declared size limit.
    """

    max_size_bytes: int = PLATFORM_DEFAULT_MAX_FILE_BYTES

    def __get_pydantic_json_schema__(self, core_schema: Any, handler: Any) -> Any:
        schema = handler(core_schema)
        schema["x-agent-file-path"] = {"max_size_bytes": self.max_size_bytes}
        return schema
