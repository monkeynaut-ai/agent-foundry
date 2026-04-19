"""Base classes for markdown-document templates.

MarkdownHeader is the base for any heading-shaped sub-document; declares the
required `title: str` field. MarkdownDocument is the top-level base; adds
the optional `frontmatter` field. Both register a __pydantic_init_subclass__
hook (added in a later task) that runs structural meta-validation at
class-definition time.
"""

from __future__ import annotations

from pydantic import BaseModel


class MarkdownHeader(BaseModel):
    """Base class for any heading-shaped sub-document.

    Declares a required `title: str` field that carries the container's
    heading text. Body fields are everything except `title`. The body
    field-order rule (non-heading fields must precede heading-introducing
    fields) is enforced by the meta-validator.
    """

    title: str


class MarkdownDocument(MarkdownHeader):
    """Base class for top-level markdown documents.

    Adds an optional `frontmatter: BaseModel | None = None` field. Subclasses
    may override this with a more specific BaseModel schema. The renderer
    always emits frontmatter at the very top of the document, before the
    title heading.
    """

    frontmatter: BaseModel | None = None
