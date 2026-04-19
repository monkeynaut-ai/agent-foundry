"""Annotation dataclasses attached to template-model fields via Annotated[T, ...].

These are plain Python objects (not Pydantic models). Pydantic stores them on
fields; the renderer / parser / validator engines read them via
`model_fields[name].metadata` at runtime.

All annotations are frozen so they are hashable and can be used as dict keys
or set members. The dataclass `eq=True` (default) ensures equal-config
annotations compare equal, which simplifies testing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AsHeading:
    """Render a `str` body field as a heading whose body is the field value
    (raw markdown text). Heading text is derived from the field name
    (snake_case → Title Case). No parameters in Phase 1."""


@dataclass(frozen=True)
class AsCodeBlock:
    """Render a `str` body field as a fenced code block. `language` becomes
    the fence's language tag; None emits an unfenced-language code block."""

    language: str | None = None


@dataclass(frozen=True)
class AsTable:
    """Render a `list[BaseModel-with-scalars]` body field as a markdown table.
    Columns are derived from the inner model's field names (in declaration
    order); each list item becomes one row."""


@dataclass(frozen=True)
class AsBulletList:
    """Render a `list[str]` body field as a bullet list."""


@dataclass(frozen=True)
class AsNumberedList:
    """Render a `list[str]` body field as a numbered list."""


@dataclass(frozen=True)
class TextTemplate:
    """Format a heading-text field using a template.

    Two contexts:
      - On a `MarkdownHeader.title` field (str): `{value}` substitutes the
        field value; `{ordinal}` substitutes the 1-based list index when
        the parent is a list.
      - On a heading-introducing list-wrapper field (list[MarkdownHeader-subclass]):
        the template is a literal that overrides the default field-name-derived
        wrapper text. Placeholders do not apply (the field value is a list,
        not a formattable string).
    """

    template: str
