"""Heading-field introspection for markdown template models.

``template_fields(ModelClass)`` returns metadata about the body heading
sections of a ``MarkdownHeader`` (or ``MarkdownDocument``) subclass — the
heading text each body field renders as, paired with the field's Pydantic
description.

Intended for consumption inside Jinja templates (via ``archetype.templating``)
or any other code that needs to enumerate a model's sections without walking
``model_fields`` directly:

    {% for field in template_fields(FeatureDefinition) %}
    - **{{ field.heading }}** — {{ field.description }}
    {% endfor %}

Supported field shapes (Slice 1):
  - ``Annotated[str, AsHeading()]`` — heading text is Title Case of field name.
  - Field typed as a ``MarkdownHeader`` subclass — heading text is the
    subclass's ``title`` field default value.

Structural fields ``title`` and ``frontmatter`` are skipped. Any other
field shape raises ``ValueError`` so the limitation is visible and future
extensions are deliberate.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_core import PydanticUndefined

from archetype.markdown._shared import get_role_annotation, snake_to_title
from archetype.markdown.annotations import AsHeading
from archetype.markdown.template_model import MarkdownHeader


@dataclass(frozen=True)
class FieldInfo:
    """Metadata for one heading-shaped body section of a template model.

    - ``heading``: the rendered heading text (without the ``#`` prefix).
    - ``description``: the field's Pydantic ``Field(description=...)``
      value, or ``None`` if the field has no description.
    """

    heading: str
    description: str | None


def template_fields(model_class: type[MarkdownHeader]) -> list[FieldInfo]:
    """Return per-section heading metadata for a ``MarkdownHeader`` subclass.

    Skips structural fields (``title``, ``frontmatter``). For each remaining
    body field, resolves heading text and returns a ``FieldInfo``. Raises
    ``ValueError`` on any field shape the accessor does not know how to
    describe.
    """

    result: list[FieldInfo] = []
    for name, field in model_class.model_fields.items():
        if name in ("title", "frontmatter"):
            continue

        heading = _resolve_heading(model_class, name, field)
        description = field.description
        result.append(FieldInfo(heading=heading, description=description))

    return result


def _resolve_heading(model_class: type[MarkdownHeader], field_name: str, field: object) -> str:
    """Resolve heading text for one body field, or raise ValueError if the
    field's shape is not supported."""

    annotation = get_role_annotation(field)

    # Shape 1: Annotated[str, AsHeading()] → Title Case of field name.
    if isinstance(annotation, AsHeading):
        return snake_to_title(field_name)

    # Shape 2: field typed as a MarkdownHeader subclass → subclass's title default.
    field_type = getattr(field, "annotation", None)
    if isinstance(field_type, type) and issubclass(field_type, MarkdownHeader):
        title_field = field_type.model_fields.get("title")
        if title_field is None or title_field.default is PydanticUndefined:
            raise ValueError(
                f"{model_class.__name__}.{field_name} is typed as "
                f"{field_type.__name__}, which has no default value for its "
                f"`title` field. template_fields() derives the heading from "
                f"the subclass's title default; give {field_type.__name__}.title "
                f'a default (e.g. `title: str = "Section Name"`), or use '
                f"Annotated[str, AsHeading()] instead."
            )
        default = title_field.default
        if not isinstance(default, str):
            raise ValueError(
                f"{model_class.__name__}.{field_name}: "
                f"{field_type.__name__}.title default is {default!r}, "
                f"expected a string."
            )
        return default

    # Any other shape is not supported.
    raise ValueError(
        f"{model_class.__name__}.{field_name} has a field shape "
        f"template_fields() does not support. Supported shapes are "
        f"Annotated[str, AsHeading()] and fields typed as a MarkdownHeader "
        f"subclass with a `title` default. Got annotation={annotation!r}, "
        f"type={field_type!r}."
    )
