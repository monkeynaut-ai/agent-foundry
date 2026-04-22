"""Internal shared helpers used by renderer, projector, and meta-validation.

These helpers form the render/parse contract: both sides MUST derive identical
heading text from the same field name and resolve the same wrapper text from
TextTemplate annotations. Centralizing them here prevents silent divergence.
"""

from __future__ import annotations

from archetype.markdown.annotations import (
    AsBulletList,
    AsCodeBlock,
    AsHeading,
    AsNumberedList,
    AsTable,
    TextTemplate,
)

# Annotation types that DO NOT open a heading scope.
_NON_HEADING_ANNOTATIONS: tuple[type, ...] = (
    AsCodeBlock,
    AsTable,
    AsBulletList,
    AsNumberedList,
)


def snake_to_title(name: str) -> str:
    """Convert snake_case to Title Case (e.g. 'change_set_name' → 'Change Set Name').

    Used by both the renderer (to emit headings from field names) and the
    projector (to look up matching headings). MUST stay in lockstep with the
    parser's matching logic, which is why it lives here, not in either module.
    """
    return " ".join(word.capitalize() for word in name.split("_"))


def resolve_wrapper_text(field_name: str, field: object) -> str:
    """Resolve the wrapper-heading text for a list[MarkdownHeader-subclass]
    body field. TextTemplate annotation (literal-only on lists; placeholders
    do not apply) overrides the snake_to_title default."""
    metadata = getattr(field, "metadata", []) or []
    for m in metadata:
        if isinstance(m, TextTemplate):
            return m.template
    return snake_to_title(field_name)


def get_role_annotation(field: object) -> object | None:
    """Extract the first markdown-role annotation from the field's metadata,
    or None if the field has no role annotation. Returns instances of
    AsHeading, AsCodeBlock, AsTable, AsBulletList, AsNumberedList, or
    TextTemplate."""
    metadata = getattr(field, "metadata", []) or []
    for m in metadata:
        if isinstance(m, (*_NON_HEADING_ANNOTATIONS, AsHeading, TextTemplate)):
            return m
    return None
