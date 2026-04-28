"""Public parse-and-validate entry point."""

from __future__ import annotations

from archetype.markdown._ast_normalizer import normalize
from archetype.markdown._projector import project_to_model
from archetype.markdown.template_model import MarkdownHeader


def validate_markdown[T: MarkdownHeader](
    markdown: str,
    model_class: type[T],
) -> T:
    """Parse the given markdown text, validate it against the template model,
    and return a populated instance of ``model_class``. Raises
    MarkdownValidationError on failure with a field-localized message."""

    doc = normalize(markdown)
    return project_to_model(doc, model_class)
