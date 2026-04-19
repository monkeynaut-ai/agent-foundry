"""Tests for the deterministic renderer."""

from __future__ import annotations

from agent_foundry.markdown.renderer import render_template
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
