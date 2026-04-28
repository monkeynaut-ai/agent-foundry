"""Walk an element tree and construct a populated domain-model instance.

The projector reads the model class's field declarations + annotations and
locates the corresponding subtree in the element tree. Strict order: model
field order must match the order of matching elements in the document.
Unmodeled elements are skipped (passthrough).
"""

from __future__ import annotations

from typing import get_args, get_origin

from pydantic import BaseModel
from pydantic import ValidationError as _PydanticValidationError

from archetype.markdown._ast_normalizer import NormalizedDocument
from archetype.markdown._shared import get_role_annotation, resolve_wrapper_text, snake_to_title
from archetype.markdown.annotations import (
    AsBulletList,
    AsCodeBlock,
    AsHeading,
    AsNumberedList,
    AsTable,
)
from archetype.markdown.elements import (
    BlockElement,
    MarkdownBulletList,
    MarkdownCodeBlock,
    MarkdownHeading,
    MarkdownNumberedList,
    MarkdownParagraph,
    MarkdownTable,
)
from archetype.markdown.errors import MarkdownValidationError
from archetype.markdown.template_model import MarkdownDocument, MarkdownHeader


def project_to_model[T: MarkdownHeader](
    doc: NormalizedDocument,
    model_class: type[T],
) -> T:
    """Project a normalized document onto a domain model instance of ``model_class``."""

    if not doc.blocks or not isinstance(doc.blocks[0], MarkdownHeading):
        first_kind = type(doc.blocks[0]).__name__ if doc.blocks else "empty document"
        raise MarkdownValidationError(
            f"Expected a top-level heading at start of document for "
            f"{model_class.__name__}.title; found {first_kind}."
        )
    top_heading = doc.blocks[0]
    raw_title = _extract_title_value(top_heading.text, model_class)
    instance_kwargs: dict = {"title": raw_title}

    if issubclass(model_class, MarkdownDocument) and doc.frontmatter is not None:
        fm_field_type = model_class.model_fields["frontmatter"].annotation
        fm_class = _extract_basemodel_arg(fm_field_type)
        if fm_class is not None:
            try:
                instance_kwargs["frontmatter"] = fm_class.model_validate(doc.frontmatter.parsed)
            except _PydanticValidationError as exc:
                raise MarkdownValidationError(
                    f"{model_class.__name__}.frontmatter: YAML content does not match "
                    f"{fm_class.__name__} schema. {exc}"
                ) from exc

    body_blocks = top_heading.body
    cursor = 0
    for name, field in model_class.model_fields.items():
        if name in ("title", "frontmatter"):
            continue
        cursor, value = _project_body_field(name, field, body_blocks, cursor, model_class)
        if value is not None:
            instance_kwargs[name] = value

    return model_class(**instance_kwargs)


def _project_body_field(
    name: str,
    field: object,
    blocks: list[BlockElement],
    cursor: int,
    model_class: type,
) -> tuple[int, object]:
    ann = get_role_annotation(field)
    field_type = field.annotation  # type: ignore[attr-defined]

    if isinstance(ann, AsHeading):
        expected_text = snake_to_title(name)
        idx, heading = _find_next_heading(blocks, cursor, expected_text, model_class, name)
        body_text = _serialize_block_body(heading)
        return idx + 1, body_text

    if isinstance(ann, AsCodeBlock):
        idx, code = _find_next_of_type(blocks, cursor, MarkdownCodeBlock, model_class, name)
        return idx + 1, code.content  # type: ignore[attr-defined]

    if isinstance(ann, AsBulletList):
        # An empty list produces no element in the rendered markdown; treat a
        # missing BulletList as an empty list rather than a validation error.
        result = _find_next_of_type_optional(blocks, cursor, MarkdownBulletList)
        if result is None:
            return cursor, []
        idx, bl = result
        return idx + 1, bl.items  # type: ignore[attr-defined]

    if isinstance(ann, AsNumberedList):
        # Same as AsBulletList: an empty list renders as nothing, so absence
        # of the element is valid and represents [].
        result = _find_next_of_type_optional(blocks, cursor, MarkdownNumberedList)
        if result is None:
            return cursor, []
        idx, nl = result
        return idx + 1, nl.items  # type: ignore[attr-defined]

    if isinstance(ann, AsTable):
        idx, t = _find_next_of_type(blocks, cursor, MarkdownTable, model_class, name)
        inner = get_args(field_type)[0]
        expected_cols = [snake_to_title(k) for k in _field_keys(inner)]
        if t.columns != expected_cols:  # type: ignore[attr-defined]
            raise MarkdownValidationError(
                f"{model_class.__name__}.{name}: table column mismatch. "
                f"Expected columns {expected_cols}, found {t.columns}. "  # type: ignore[attr-defined]
                f"Columns must match the inner model's field names in declaration order."
            )
        rows = [
            inner.model_validate(
                dict(zip(_field_keys(inner), row.cells, strict=False))  # type: ignore[attr-defined]
            )
            for row in t.rows  # type: ignore[attr-defined]
        ]
        return idx + 1, rows

    if isinstance(field_type, type) and issubclass(field_type, MarkdownHeader):
        idx, heading = _find_next_heading(blocks, cursor, None, model_class, name)
        sub_doc = NormalizedDocument(frontmatter=None, blocks=[heading])
        nested_instance = project_to_model(sub_doc, field_type)
        return idx + 1, nested_instance

    if get_origin(field_type) is list:
        args = get_args(field_type)
        if args and isinstance(args[0], type) and issubclass(args[0], MarkdownHeader):
            wrapper_text = resolve_wrapper_text(name, field)
            idx, wrapper = _find_next_heading(blocks, cursor, wrapper_text, model_class, name)
            items = []
            for child in wrapper.body:
                if isinstance(child, MarkdownHeading):
                    sub_doc = NormalizedDocument(frontmatter=None, blocks=[child])
                    items.append(project_to_model(sub_doc, args[0]))
            return idx + 1, items

    return cursor, None


def _find_next_heading(
    blocks: list[BlockElement],
    cursor: int,
    expected_text: str | None,
    model_class: type,
    field_name: str,
) -> tuple[int, MarkdownHeading]:
    # Heading matching is case-insensitive via casefold. Authors routinely
    # write sentence-case headings (`## Problem statement`) while the
    # model's `snake_to_title` default produces Title Case (`Problem
    # Statement`). Treating these as equivalent at parse time avoids
    # rejecting otherwise-correct documents over casing. The title value
    # stored on the resulting instance preserves the source casing, so
    # re-render reproduces whatever form the author chose.
    target = expected_text.casefold() if expected_text is not None else None
    for i in range(cursor, len(blocks)):
        b = blocks[i]
        if isinstance(b, MarkdownHeading) and (target is None or b.text.casefold() == target):
            return i, b
    expected_clause = f"with text {expected_text!r}" if expected_text else ""
    raise MarkdownValidationError(
        f"{model_class.__name__}.{field_name}: expected heading "
        f"{expected_clause} not found after position {cursor}."
    )


def _find_next_of_type(
    blocks: list[BlockElement],
    cursor: int,
    element_type: type,
    model_class: type,
    field_name: str,
) -> tuple[int, BlockElement]:
    for i in range(cursor, len(blocks)):
        if isinstance(blocks[i], element_type):
            return i, blocks[i]
    raise MarkdownValidationError(
        f"{model_class.__name__}.{field_name}: expected {element_type.__name__} "
        f"not found after position {cursor}."
    )


def _find_next_of_type_optional(
    blocks: list[BlockElement],
    cursor: int,
    element_type: type,
) -> tuple[int, BlockElement] | None:
    """Like `_find_next_of_type` but returns None instead of raising when the
    element is absent. Used for list fields where an empty list renders as no
    element in the document."""
    for i in range(cursor, len(blocks)):
        if isinstance(blocks[i], element_type):
            return i, blocks[i]
    return None


def _field_keys(model: type[BaseModel]) -> list[str]:
    return list(model.model_fields.keys())


def _serialize_block_body(heading: MarkdownHeading, *, _depth: int = 0) -> str:
    """Serialize the body of a heading back to markdown text. Used to reconstitute
    an `Annotated[str, AsHeading()]` field's value.

    `_depth` tracks the nesting of sub-headings inside the body. The first level
    of sub-heading emits at `##` (depth 0); each recursive level adds one `#`.
    Without depth tracking, multi-level heading bodies collapse to a single
    sibling level on round-trip.

    Note: depths beyond 4 would produce heading levels > 6 (markdown maximum),
    but such deep nesting is uncommon in practice and text remains readable.
    """
    parts: list[str] = []
    for b in heading.body:
        if isinstance(b, MarkdownParagraph):
            parts.append(b.content)
        elif isinstance(b, MarkdownHeading):
            level = 2 + _depth
            parts.append(f"{'#' * level} {b.text}")
            sub_body = _serialize_block_body(b, _depth=_depth + 1)
            if sub_body:
                parts.append(sub_body)
        elif isinstance(b, MarkdownCodeBlock):
            lang = b.language or ""
            parts.append(f"```{lang}\n{b.content}```")
        elif isinstance(b, MarkdownBulletList):
            parts.append("\n".join(f"- {item}" for item in b.items))
        elif isinstance(b, MarkdownNumberedList):
            parts.append("\n".join(f"{i + 1}. {item}" for i, item in enumerate(b.items)))
        elif isinstance(b, MarkdownTable):
            parts.append(_serialize_table(b))
    return "\n\n".join(parts).strip()


def _serialize_table(t: MarkdownTable) -> str:
    header = "| " + " | ".join(t.columns) + " |"
    sep = "|" + "|".join(["---"] * len(t.columns)) + "|"
    rows = ["| " + " | ".join(r.cells) + " |" for r in t.rows]
    return "\n".join([header, sep, *rows])


def _extract_basemodel_arg(field_type: object) -> type[BaseModel] | None:
    args = get_args(field_type)
    for a in args:
        if isinstance(a, type) and issubclass(a, BaseModel):
            return a
    return None


def _extract_title_value(heading_text: str, model_class: type[MarkdownHeader]) -> str:
    """Reverse-extract the {value} portion from a TextTemplate'd title."""
    from archetype.markdown.annotations import TextTemplate

    title_field = model_class.model_fields.get("title")
    if not title_field:
        return heading_text
    for m in title_field.metadata or []:
        if isinstance(m, TextTemplate):
            return _reverse_text_template(m.template, heading_text)
    return heading_text


def _reverse_text_template(template: str, heading_text: str) -> str:
    import re

    if "{value}" not in template:
        return heading_text
    pattern = re.escape(template)
    pattern = pattern.replace(re.escape("{value}"), r"(?P<value>.*)")
    pattern = pattern.replace(re.escape("{ordinal}"), r"\d+")
    m = re.fullmatch(pattern, heading_text)
    if not m:
        return heading_text
    return m.group("value")
