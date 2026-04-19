"""Class-definition-time meta-validation for MarkdownHeader / MarkdownDocument
subclasses.

Triggered by the __pydantic_init_subclass__ hook on MarkdownHeader. Walks the
subclass's model_fields and enforces:
  1. Title rule          — title:str required (inherited; not overridden to non-str)
  2. Body order rule     — non-heading body fields must precede heading-introducing ones
  3. Frontmatter rule    — only on MarkdownDocument subclasses; first field; type BaseModel|None
  4. Type-compat rule    — every annotation has an allowed underlying type

Errors raise MarkdownTemplateError immediately so an offending class never
reaches runtime use.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_foundry.markdown.errors import MarkdownTemplateError

if TYPE_CHECKING:
    from agent_foundry.markdown.template_model import MarkdownHeader


def validate_template_class(cls: type[MarkdownHeader]) -> None:
    """Run all meta-validation rules against a MarkdownHeader/MarkdownDocument subclass.
    Called from __pydantic_init_subclass__. Raises MarkdownTemplateError on any rule
    violation, including the offending field name and a fix suggestion in the message."""

    _check_title_rule(cls)
    # Subsequent rules added in following tasks:
    #   _check_body_order_rule(cls)
    #   _check_frontmatter_rule(cls)
    #   _check_type_compatibility_rule(cls)


def _check_title_rule(cls: type[MarkdownHeader]) -> None:
    """Title field must exist and be of type str."""
    fields = cls.model_fields
    if "title" not in fields:
        raise MarkdownTemplateError(
            f"{cls.__name__} is missing required 'title' field. "
            f"All MarkdownHeader subclasses inherit title:str; do not delete it."
        )
    title_field = fields["title"]
    if title_field.annotation is not str:
        raise MarkdownTemplateError(
            f"{cls.__name__}.title has type {title_field.annotation!r}, "
            f"expected str. The title field must remain a str (you may attach "
            f"annotations like TextTemplate via Annotated[str, TextTemplate(...)])."
        )
