"""Error hierarchy for the archetype.markdown package."""

from __future__ import annotations


class MarkdownError(Exception):
    """Base class for all markdown machinery errors."""


class MarkdownTemplateError(MarkdownError, TypeError):
    """Raised at class-definition time when a MarkdownHeader/MarkdownDocument
    subclass violates a structural rule (title required, body order, frontmatter
    placement, type-annotation compatibility).

    Inherits from TypeError because the violation is a class-construction problem,
    not a runtime data problem.
    """


class MarkdownValidationError(MarkdownError):
    """Raised when a produced markdown document fails to validate against a
    template model (missing required heading, mismatched order, etc.)."""


class MarkdownExtractionError(MarkdownError):
    """Raised when extract_subtree cannot satisfy its lookup
    (no matching heading, multiple matches, etc.)."""
