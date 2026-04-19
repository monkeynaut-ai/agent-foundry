"""Tests for the deterministic renderer."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from agent_foundry.markdown.annotations import AsBulletList, AsCodeBlock, AsNumberedList, AsTable
from agent_foundry.markdown.renderer import render_template
from agent_foundry.markdown.template_model import MarkdownHeader
from tests.agent_foundry.markdown.fixtures.sample_models import HeaderWithSummary, SimpleHeader


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
