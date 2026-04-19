"""Markdown element classes — the parser's typed intermediate representation.

Application authors do not normally import these classes directly. They interact
with the platform through MarkdownHeader, MarkdownDocument, and the annotation
library. Element classes are exported only for advanced use (tests, debugging).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class MarkdownKind(StrEnum):
    """Discriminator values for the BlockElement union."""

    HEADING = "heading"
    CODE_BLOCK = "code_block"
    TABLE = "table"
    BULLET_LIST = "bullet_list"
    NUMBERED_LIST = "numbered_list"
    FRONTMATTER = "frontmatter"


class MarkdownHeading(BaseModel):
    """A parsed markdown heading and its scoped body content.

    `text` is the heading's title text (without the `#` prefix).
    `body` is everything inside the heading's scope, recursively parsed
    into `BlockElement` instances. Note: heading level is intentionally
    NOT carried on this element; level is an AST concern used only by
    the subtree extractor.
    """

    kind: Literal[MarkdownKind.HEADING] = MarkdownKind.HEADING
    text: str
    body: list[BlockElement] = Field(default_factory=list)


class MarkdownCodeBlock(BaseModel):
    """A parsed fenced code block.

    `language` is the fence's language tag (e.g. 'python'); None when no
    language tag was present (``` followed immediately by code).
    `content` is the raw text inside the fences.
    """

    kind: Literal[MarkdownKind.CODE_BLOCK] = MarkdownKind.CODE_BLOCK
    language: str | None = None
    content: str


# Forward-declared until other element classes are added.
BlockElement = Annotated[
    MarkdownHeading | MarkdownCodeBlock,
    Field(discriminator="kind"),
]

MarkdownHeading.model_rebuild()
