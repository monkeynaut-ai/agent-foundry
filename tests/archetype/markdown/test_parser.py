"""End-to-end tests for the public parse-and-validate function."""

from __future__ import annotations

import pytest

from archetype.markdown.errors import MarkdownValidationError
from archetype.markdown.parser import validate_markdown
from archetype.markdown.renderer import render_instance
from tests.archetype.markdown.fixtures.sample_models import (
    Finding,
    HeaderWithSummary,
    ReviewerMetadata,
    ReviewerOutput,
)


class TestValidateMarkdown:
    def test_simple_header_with_summary_round_trip(self):
        original = HeaderWithSummary(title="Doc", summary="The work is good.")
        rendered = render_instance(original)
        parsed = validate_markdown(rendered, HeaderWithSummary)
        assert parsed.title == "Doc"
        assert "The work is good." in parsed.summary

    def test_full_reviewer_output_round_trip(self):
        original = ReviewerOutput(
            title="Review of cs7-plan4",
            frontmatter=ReviewerMetadata(change_set_name="cs7", commit_range="abc..def"),
            next_steps=["A", "B"],
            summary="Looks good.",
            findings=[
                Finding(
                    title="t1",
                    code="x = 1",
                    tags=["x"],
                    description="d",
                    rationale="r",
                ),
            ],
        )
        rendered = render_instance(original)
        parsed = validate_markdown(rendered, ReviewerOutput)
        assert parsed.title == "Review of cs7-plan4"
        assert parsed.frontmatter is not None
        assert parsed.frontmatter.change_set_name == "cs7"
        assert parsed.next_steps == ["A", "B"]
        assert len(parsed.findings) == 1
        assert parsed.findings[0].title == "t1"

    def test_invalid_markdown_raises_validation_error(self):
        with pytest.raises(MarkdownValidationError):
            validate_markdown("just text\n", HeaderWithSummary)

    def test_malformed_frontmatter_yaml_raises_markdown_validation_error(self):
        bad = "---\nkey: [unclosed\n---\n\n# Doc\n\n## Summary\n\ntext\n"
        with pytest.raises(MarkdownValidationError, match=r"[Ff]rontmatter"):
            validate_markdown(bad, HeaderWithSummary)

    def test_frontmatter_schema_mismatch_raises_markdown_validation_error(self):
        # ReviewerMetadata requires both change_set_name and commit_range.
        # Omit commit_range to force a pydantic.ValidationError at the boundary.
        bad = (
            "---\nchange_set_name: cs7\n---\n\n# Doc\n\n1. step\n\n## Summary\n\nx\n\n## Findings\n"
        )
        with pytest.raises(MarkdownValidationError, match=r"[Ff]rontmatter"):
            validate_markdown(bad, ReviewerOutput)
