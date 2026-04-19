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
    PARAGRAPH = "paragraph"


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


class MarkdownTableRow(BaseModel):
    """One row of a parsed markdown table. Cells are flat strings; rich
    inline content within cells is flattened to plain text in Phase 1."""

    cells: list[str]


class MarkdownTable(BaseModel):
    """A parsed GFM markdown table.

    `columns` are the header labels in column order.
    `rows` are the data rows; each row's cells must align with columns.
    """

    kind: Literal[MarkdownKind.TABLE] = MarkdownKind.TABLE
    columns: list[str]
    rows: list[MarkdownTableRow]


class MarkdownBulletList(BaseModel):
    """A parsed unordered (bullet) list. Items are flat strings; nested lists
    are not supported in Phase 1."""

    kind: Literal[MarkdownKind.BULLET_LIST] = MarkdownKind.BULLET_LIST
    items: list[str]


class MarkdownNumberedList(BaseModel):
    """A parsed ordered (numbered) list. Items are flat strings; nested lists
    are not supported in Phase 1."""

    kind: Literal[MarkdownKind.NUMBERED_LIST] = MarkdownKind.NUMBERED_LIST
    items: list[str]


class MarkdownFrontmatter(BaseModel):
    """A parsed YAML frontmatter block. Document-root-only — never appears
    inside a heading body (and is excluded from the BlockElement union).

    `raw_yaml` is the literal text between the opening and closing `---` fences.
    `parsed` is the YAML decoded into a dict; the projector then validates this
    dict against the model's `frontmatter` field type (a typed BaseModel).
    """

    kind: Literal[MarkdownKind.FRONTMATTER] = MarkdownKind.FRONTMATTER
    raw_yaml: str
    parsed: dict


class MarkdownParagraph(BaseModel):
    """A parsed paragraph of inline text. Internal AST element used by the
    AST normalizer to preserve prose content inside heading bodies. Not
    referenced from any annotation; not part of the public API."""

    kind: Literal[MarkdownKind.PARAGRAPH] = MarkdownKind.PARAGRAPH
    content: str


# Forward-declared until other element classes are added.
BlockElement = Annotated[
    MarkdownHeading
    | MarkdownCodeBlock
    | MarkdownTable
    | MarkdownBulletList
    | MarkdownNumberedList
    | MarkdownParagraph,
    Field(discriminator="kind"),
]

MarkdownHeading.model_rebuild()
