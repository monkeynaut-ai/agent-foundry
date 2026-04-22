"""Tests for the deterministic renderer."""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel

from archetype.markdown.annotations import (
    AsBulletList,
    AsCodeBlock,
    AsHeading,
    AsNumberedList,
    AsTable,
)
from archetype.markdown.errors import MarkdownTemplateError
from archetype.markdown.renderer import render_instance, render_template
from archetype.markdown.template_model import MarkdownHeader
from tests.archetype.markdown.fixtures.sample_models import (
    Finding,
    HeaderWithSummary,
    ReviewerMetadata,
    ReviewerOutput,
    SimpleHeader,
)


class TestRenderTemplateSimpleHeader:
    """Skeleton output for the smallest possible header."""

    def test_simple_header_emits_h1_placeholder(self):
        out = render_template(SimpleHeader)
        # Top-level header at level 1; title placeholder uses field-description style.
        assert out.startswith("# ")
        assert out.endswith("\n")


class TestRenderHeadingBodyFields:
    """AsHeading on str body field renders as `## FieldName` + placeholder body."""

    def test_summary_field_renders_at_level_2(self):
        out = render_template(HeaderWithSummary)
        # Title at level 1, summary at level 2.
        assert "# " in out
        assert "## Summary" in out

    def test_summary_field_field_name_is_title_cased(self):
        # snake_case → Title Case
        out = render_template(HeaderWithSummary)
        assert "## Summary" in out
        assert "## summary" not in out


class TestRenderNonHeadingBodyFields:
    """Code blocks, bullet lists, numbered lists render as their markdown forms."""

    def test_code_block_template_emits_fenced_block(self):
        class WithCode(MarkdownHeader):
            snippet: Annotated[str, AsCodeBlock(language="python")]

        out = render_template(WithCode)
        assert "```python" in out
        assert "```" in out

    def test_bullet_list_template_emits_dash_placeholder(self):
        class WithBullets(MarkdownHeader):
            tags: Annotated[list[str], AsBulletList()]

        out = render_template(WithBullets)
        assert "- " in out

    def test_numbered_list_template_emits_one_dot_placeholder(self):
        class WithNumbers(MarkdownHeader):
            steps: Annotated[list[str], AsNumberedList()]

        out = render_template(WithNumbers)
        assert "1. " in out


class TestRenderTable:
    def test_table_template_emits_pipe_header_and_separator(self):
        class Row(BaseModel):
            path: str
            lines: int

        class WithTable(MarkdownHeader):
            files: Annotated[list[Row], AsTable()]

        out = render_template(WithTable)
        assert "| Path | Lines |" in out
        assert "|---|---|" in out


class TestRenderHeadingIntroducingFields:
    def test_list_of_finding_template_emits_wrapper_heading(self):
        class WithFindings(MarkdownHeader):
            findings: list[Finding]

        out = render_template(WithFindings)
        assert "## Findings" in out  # wrapper heading

    def test_finding_item_template_emits_ordinal_placeholder(self):
        class WithFindings(MarkdownHeader):
            findings: list[Finding]

        out = render_template(WithFindings)
        # The Finding subdocument's title carries TextTemplate("Finding {ordinal} - {value}")
        # In skeleton form, ordinal is shown as "{ordinal}" or a literal placeholder.
        assert "Finding {ordinal}" in out or "### Finding 1" in out


class TestRenderInstance:
    def test_simple_header_with_summary(self):
        h = HeaderWithSummary(title="My Doc", summary="The work is good.")
        out = render_instance(h)
        assert out.startswith("# My Doc")
        assert "## Summary" in out
        assert "The work is good." in out

    def test_finding_uses_text_template(self):
        f = Finding(
            title="missing tests",
            code="def foo(): pass",
            tags=["test", "coverage"],
            description="No unit tests exist.",
            rationale="Project requires TDD.",
        )
        out = render_instance(f, current_level=3)
        assert "### Finding 1 - missing tests" in out
        assert "```python" in out
        assert "def foo(): pass" in out
        assert "- test" in out
        assert "- coverage" in out

    def test_full_reviewer_output_with_frontmatter(self):
        review = ReviewerOutput(
            title="Review of cs7-plan4",
            frontmatter=ReviewerMetadata(change_set_name="cs7", commit_range="abc..def"),
            next_steps=["A", "B"],
            summary="Looks good.",
            findings=[
                Finding(
                    title="t1",
                    code="x",
                    tags=[],
                    description="d",
                    rationale="r",
                )
            ],
        )
        out = render_instance(review)
        assert out.startswith("---\n")
        assert "change_set_name: cs7" in out
        assert "# Review of cs7-plan4" in out
        assert "1. A" in out
        assert "## Summary" in out
        assert "## Findings" in out
        assert "### Finding 1 - t1" in out


class TestDepthGuard:
    def test_seven_levels_deep_raises(self):
        class L7(MarkdownHeader):
            inner: Annotated[str, AsHeading()]

        class L6(MarkdownHeader):
            inner: L7

        class L5(MarkdownHeader):
            inner: L6

        class L4(MarkdownHeader):
            inner: L5

        class L3(MarkdownHeader):
            inner: L4

        class L2(MarkdownHeader):
            inner: L3

        class L1(MarkdownHeader):
            inner: L2

        with pytest.raises(MarkdownTemplateError, match="level 7"):
            render_template(L1)
