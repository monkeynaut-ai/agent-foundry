"""Tests for the deterministic renderer."""

from __future__ import annotations

from agent_foundry.markdown.renderer import render_template
from tests.agent_foundry.markdown.fixtures.sample_models import SimpleHeader


class TestRenderTemplateSimpleHeader:
    """Skeleton output for the smallest possible header."""

    def test_simple_header_emits_h1_placeholder(self):
        out = render_template(SimpleHeader)
        # Top-level header at level 1; title placeholder uses field-description style.
        assert out.startswith("# ")
        assert out.endswith("\n")
