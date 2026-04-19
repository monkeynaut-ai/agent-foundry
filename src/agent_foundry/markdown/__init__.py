"""Declarative markdown-document machinery for Agent Foundry products.

See `agent-foundry/docs/architecture/adr_markdown_template_model_shape.md` for the
architectural decision and the markdown-machinery-design document for the design.

Quick example:

    from agent_foundry.markdown import (
        MarkdownDocument, MarkdownHeader,
        AsHeading, TextTemplate,
        render_template, validate_markdown,
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
"""

from agent_foundry.markdown.annotations import (
    AsBulletList,
    AsCodeBlock,
    AsHeading,
    AsNumberedList,
    AsTable,
    TextTemplate,
)
from agent_foundry.markdown.errors import (
    MarkdownError,
    MarkdownExtractionError,
    MarkdownTemplateError,
    MarkdownValidationError,
)
from agent_foundry.markdown.extractor import extract_subtree
from agent_foundry.markdown.parser import validate_markdown
from agent_foundry.markdown.renderer import render_instance, render_template
from agent_foundry.markdown.template_model import MarkdownDocument, MarkdownHeader

__all__ = [
    "AsBulletList",
    "AsCodeBlock",
    "AsHeading",
    "AsNumberedList",
    "AsTable",
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
    "validate_markdown",
]
