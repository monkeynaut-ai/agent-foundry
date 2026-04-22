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

from types import UnionType
from typing import TYPE_CHECKING, Union, get_args, get_origin

from pydantic import BaseModel as _BaseModel

from archetype.markdown._shared import get_role_annotation
from archetype.markdown.annotations import (
    AsBulletList,
    AsCodeBlock,
    AsHeading,
    AsNumberedList,
    AsTable,
    TextTemplate,
)
from archetype.markdown.errors import MarkdownTemplateError

if TYPE_CHECKING:
    from archetype.markdown.template_model import MarkdownHeader


def validate_template_class(cls: type[MarkdownHeader]) -> None:
    """Run all meta-validation rules against a MarkdownHeader/MarkdownDocument subclass.
    Called from __pydantic_init_subclass__. Raises MarkdownTemplateError on any rule
    violation, including the offending field name and a fix suggestion in the message."""

    _check_title_rule(cls)
    _check_body_order_rule(cls)
    _check_frontmatter_rule(cls)
    _check_type_compatibility_rule(cls)


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
                f"(annotation type {type(get_role_annotation(field)).__name__}) "
                f"and follows {cls.__name__}.{seen_heading_name} "
                f"which is heading-introducing. Within a MarkdownHeader subclass's "
                f"body, all non-heading fields must precede all heading-introducing "
                f"fields. Reorder so '{name}' comes before '{seen_heading_name}', "
                f"or move '{name}' into '{seen_heading_name}''s body."
            )


def _check_frontmatter_rule(cls: type[MarkdownHeader]) -> None:
    """Frontmatter constraints:
       (a) declared (non-default) only on MarkdownDocument subclasses
       (b) when declared in the subclass body, must be the first field
       (c) type must be BaseModel | None
    Note: subclasses that inherit MarkdownDocument's default `frontmatter: BaseModel|None = None`
    without overriding it pass trivially. MarkdownDocument itself is exempt (it defines
    the canonical frontmatter field).
    """
    # Detect whether the subclass declares 'frontmatter' itself (not just inherits).
    # Use raw __annotations__ for the name-presence and ordering check (we only need
    # field names; values are strings under `from __future__ import annotations` but
    # that doesn't matter for name-based checks).
    own_annotation_names = list(getattr(cls, "__annotations__", {}).keys())
    if "frontmatter" not in own_annotation_names:
        return  # nothing declared in this subclass; rule passes

    # Rule (a): only MarkdownDocument subclasses may declare frontmatter.
    # We check by MRO class names to avoid circular import (MarkdownDocument is being
    # constructed when this runs for the first time).
    mro_names = {c.__name__ for c in cls.__mro__}
    is_markdown_document_itself = cls.__name__ == "MarkdownDocument"
    is_markdown_document_subclass = (
        "MarkdownDocument" in mro_names and not is_markdown_document_itself
    )

    if is_markdown_document_itself:
        return  # MarkdownDocument itself defines the frontmatter field; always valid.

    if not is_markdown_document_subclass:
        raise MarkdownTemplateError(
            f"{cls.__name__} declares 'frontmatter' but inherits from MarkdownHeader, "
            f"not MarkdownDocument. Frontmatter is allowed only on MarkdownDocument "
            f"subclasses. Either change the base class to MarkdownDocument, or remove "
            f"the frontmatter field."
        )

    # Rule (b): must be the first field declared in this subclass.
    if own_annotation_names[0] != "frontmatter":
        raise MarkdownTemplateError(
            f"{cls.__name__}: 'frontmatter' must be the first declared field "
            f"(currently field {own_annotation_names.index('frontmatter') + 1} of "
            f"{len(own_annotation_names)}). Move it to the top of the class body."
        )

    # Rule (c): type must be (BaseModel-subclass) | None.
    # Use model_fields (Pydantic-resolved) rather than raw annotations (string forms).
    field_type = cls.model_fields["frontmatter"].annotation  # type: ignore[attr-defined]
    if not _is_optional_basemodel(field_type):
        raise MarkdownTemplateError(
            f"{cls.__name__}.frontmatter has type {field_type!r}, expected a "
            f"BaseModel-subclass union with None (e.g. `MyFrontmatter | None`). "
        )


def _check_type_compatibility_rule(cls: type[MarkdownHeader]) -> None:
    """Each annotation has an allowed underlying type:
       AsHeading       -> str
       AsCodeBlock     -> str
       AsTable         -> list[BaseModel-subclass]
       AsBulletList    -> list[str]
       AsNumberedList  -> list[str]
       TextTemplate    -> str (title field) OR a list[MarkdownHeader-subclass] (wrapper)
    Mismatches raise MarkdownTemplateError naming the field, the annotation,
    and the allowed type.
    """
    for name, field in cls.model_fields.items():
        if name in ("title", "frontmatter"):
            continue
        ann = get_role_annotation(field)
        field_type = field.annotation
        _enforce_compat(cls, name, ann, field_type)


def _enforce_compat(cls: type, field_name: str, ann: object | None, field_type: object) -> None:
    from archetype.markdown.template_model import MarkdownHeader

    if ann is None:
        return  # untyped body field; allowed (passthrough — see body-order rule)
    if isinstance(ann, AsHeading):
        if field_type is not str:
            _raise_compat(cls, field_name, "AsHeading", "str", field_type)
    elif isinstance(ann, AsCodeBlock):
        if field_type is not str:
            _raise_compat(cls, field_name, "AsCodeBlock", "str", field_type)
    elif isinstance(ann, AsBulletList):
        if not _is_list_of(field_type, str):
            _raise_compat(cls, field_name, "AsBulletList", "list[str]", field_type)
    elif isinstance(ann, AsNumberedList):
        if not _is_list_of(field_type, str):
            _raise_compat(cls, field_name, "AsNumberedList", "list[str]", field_type)
    elif isinstance(ann, AsTable):
        if not _is_list_of_basemodel(field_type):
            _raise_compat(cls, field_name, "AsTable", "list[BaseModel]", field_type)
    elif isinstance(ann, TextTemplate) and not _is_list_of_markdown_header(
        field_type, MarkdownHeader
    ):
        # TextTemplate is allowed only on:
        #   - MarkdownHeader.title field (str) — skipped above
        #   - heading-introducing list-wrapper fields: list[MarkdownHeader-subclass]
        # Any other use is a definition-time error.
        _raise_compat(
            cls,
            field_name,
            "TextTemplate",
            "MarkdownHeader.title (str) or list[MarkdownHeader-subclass]",
            field_type,
        )


def _is_list_of_markdown_header(field_type: object, markdown_header_cls: type) -> bool:
    if get_origin(field_type) is not list:
        return False
    args = get_args(field_type)
    return len(args) == 1 and isinstance(args[0], type) and issubclass(args[0], markdown_header_cls)


def _is_list_of(field_type: object, expected: type) -> bool:
    if get_origin(field_type) is not list:
        return False
    args = get_args(field_type)
    return len(args) == 1 and args[0] is expected


def _is_list_of_basemodel(field_type: object) -> bool:
    if get_origin(field_type) is not list:
        return False
    args = get_args(field_type)
    return len(args) == 1 and isinstance(args[0], type) and issubclass(args[0], _BaseModel)


def _raise_compat(
    cls: type,
    field_name: str,
    ann_name: str,
    expected: str,
    actual: object,
) -> None:
    raise MarkdownTemplateError(
        f"{cls.__name__}.{field_name}: {ann_name} requires field type {expected}, "
        f"got {actual!r}. Either change the field's type, or use a different annotation."
    )


def _is_optional_basemodel(annotation: object) -> bool:
    """True iff the annotation is `BaseModel-subclass | None`."""
    origin = get_origin(annotation)
    if origin not in (Union, UnionType):
        return False
    args = get_args(annotation)
    if len(args) != 2:
        return False
    has_none = type(None) in args
    has_basemodel = any(isinstance(a, type) and issubclass(a, _BaseModel) for a in args)
    return has_none and has_basemodel


def _is_heading_introducing(field: object) -> bool:
    """A body field is heading-introducing if it has AsHeading annotation,
    OR its type is a MarkdownHeader subclass, OR its type is list[MarkdownHeader-subclass]."""

    from archetype.markdown.template_model import MarkdownHeader

    ann = get_role_annotation(field)
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
