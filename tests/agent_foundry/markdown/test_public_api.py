"""Tests for the public API surface of agent_foundry.markdown."""

from __future__ import annotations


class TestPublicAPI:
    """Importing from agent_foundry.markdown reaches every documented symbol."""

    def test_all_documented_symbols_importable(self):
        from agent_foundry.markdown import (
            AsBulletList,
            AsCodeBlock,
            AsHeading,
            AsNumberedList,
            AsTable,
            MarkdownDocument,
            MarkdownExtractionError,
            MarkdownHeader,
            MarkdownTemplateError,
            MarkdownValidationError,
            TextTemplate,
            extract_subtree,
            render_instance,
            render_template,
            validate_markdown,
        )

        # Existence of each symbol is the assertion.
        assert all(
            [
                MarkdownHeader,
                MarkdownDocument,
                AsHeading,
                AsCodeBlock,
                AsTable,
                AsBulletList,
                AsNumberedList,
                TextTemplate,
                render_template,
                render_instance,
                validate_markdown,
                extract_subtree,
                MarkdownTemplateError,
                MarkdownValidationError,
                MarkdownExtractionError,
            ]
        )
