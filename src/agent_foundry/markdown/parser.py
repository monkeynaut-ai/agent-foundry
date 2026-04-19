"""Public parse-and-validate entry point."""

from __future__ import annotations

from agent_foundry.markdown._ast_normalizer import normalize
from agent_foundry.markdown._projector import project_to_model
from agent_foundry.markdown.template_model import MarkdownHeader


def validate_markdown(
    markdown: str,
    model_class: type[MarkdownHeader],
) -> MarkdownHeader:
    """Parse the given markdown text, validate it against the template model,
    and return a populated instance. Raises MarkdownValidationError on failure
    with a field-localized message."""

    doc = normalize(markdown)
    return project_to_model(doc, model_class)
