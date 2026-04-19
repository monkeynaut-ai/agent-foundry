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

from typing import TYPE_CHECKING, get_args, get_origin

from agent_foundry.markdown.annotations import (
    AsBulletList,
    AsCodeBlock,
    AsHeading,
    AsNumberedList,
    AsTable,
)
from agent_foundry.markdown.errors import MarkdownTemplateError

if TYPE_CHECKING:
    from agent_foundry.markdown.template_model import MarkdownHeader

# Annotation types that DO NOT open a heading scope.
_NON_HEADING_ANNOTATIONS: tuple[type, ...] = (
    AsCodeBlock,
    AsTable,
    AsBulletList,
    AsNumberedList,
)


def validate_template_class(cls: type[MarkdownHeader]) -> None:
    """Run all meta-validation rules against a MarkdownHeader/MarkdownDocument subclass.
    Called from __pydantic_init_subclass__. Raises MarkdownTemplateError on any rule
    violation, including the offending field name and a fix suggestion in the message."""

    _check_title_rule(cls)
    _check_body_order_rule(cls)
    # Subsequent rules added in following tasks:
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


def _check_body_order_rule(cls: type[MarkdownHeader]) -> None:
    """Within the body (every field except 'title' and 'frontmatter'),
    non-heading fields must precede heading-introducing fields."""

    seen_heading = False
    seen_heading_name: str | None = None
    for name, field in cls.model_fields.items():
        if name in ("title", "frontmatter"):
            continue
        is_heading = _is_heading_introducing(field)
        if is_heading:
            seen_heading = True
            seen_heading_name = name
        elif seen_heading:
            raise MarkdownTemplateError(
                f"{cls.__name__}.{name} is non-heading "
                f"(annotation type {type(_get_role_annotation(field)).__name__}) "
                f"and follows {cls.__name__}.{seen_heading_name} "
                f"which is heading-introducing. Within a MarkdownHeader subclass's "
                f"body, all non-heading fields must precede all heading-introducing "
                f"fields. Reorder so '{name}' comes before '{seen_heading_name}', "
                f"or move '{name}' into '{seen_heading_name}''s body."
            )


def _is_heading_introducing(field: object) -> bool:
    """A body field is heading-introducing if it has AsHeading annotation,
    OR its type is a MarkdownHeader subclass, OR its type is list[MarkdownHeader-subclass]."""

    from agent_foundry.markdown.template_model import MarkdownHeader

    ann = _get_role_annotation(field)
    if isinstance(ann, AsHeading):
        return True
    field_type = field.annotation  # type: ignore[attr-defined]
    if isinstance(field_type, type) and issubclass(field_type, MarkdownHeader):
        return True
    # list[MarkdownHeader-subclass]
    if get_origin(field_type) is list:
        args = get_args(field_type)
        if args and isinstance(args[0], type) and issubclass(args[0], MarkdownHeader):
            return True
    return False


def _get_role_annotation(field: object) -> object | None:
    """Extract the first markdown-role annotation from the field's metadata,
    or None if there isn't one."""

    metadata = getattr(field, "metadata", []) or []
    for m in metadata:
        if isinstance(m, (*_NON_HEADING_ANNOTATIONS, AsHeading)):
            return m
    return None
