"""Declarative markdown-document machinery for archetype.

See the architecture ADR and the markdown-machinery-design document for
context. Quick example:

    from typing import Annotated
    from archetype.markdown import (
        MarkdownDocument, MarkdownHeader,
        AsHeading, TextTemplate,
        render_template, validate_markdown,
        template_fields,
    )

    class Finding(MarkdownHeader):
        title: Annotated[str, TextTemplate("Finding {ordinal} - {value}")]
        description: Annotated[str, AsHeading()]

    class Review(MarkdownDocument):
        title: Annotated[str, TextTemplate("{value}")]
        summary: Annotated[str, AsHeading()]
        findings: list[Finding]

    template = render_template(Review)
    review = validate_markdown(produced_md, Review)
    fields = template_fields(Review)
"""

from archetype.markdown.annotations import (
    AsBulletList,
    AsCodeBlock,
    AsHeading,
    AsNumberedList,
    AsTable,
    TextTemplate,
)
from archetype.markdown.errors import (
    MarkdownError,
    MarkdownExtractionError,
    MarkdownTemplateError,
    MarkdownValidationError,
)
from archetype.markdown.extractor import extract_subtree
from archetype.markdown.introspection import FieldInfo, template_fields
from archetype.markdown.parser import validate_markdown
from archetype.markdown.renderer import render_instance, render_template
from archetype.markdown.template_model import MarkdownDocument, MarkdownHeader

__all__ = [
    "AsBulletList",
    "AsCodeBlock",
    "AsHeading",
    "AsNumberedList",
    "AsTable",
    "FieldInfo",
    "MarkdownDocument",
    "MarkdownError",
    "MarkdownExtractionError",
    "MarkdownHeader",
    "MarkdownTemplateError",
    "MarkdownValidationError",
    "TextTemplate",
    "extract_subtree",
    "render_instance",
    "render_template",
    "template_fields",
    "validate_markdown",
]
