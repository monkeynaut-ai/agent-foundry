"""Tests for the subtree extractor."""

from __future__ import annotations

import pytest

from agent_foundry.markdown.errors import MarkdownExtractionError
from agent_foundry.markdown.extractor import extract_subtree

SAMPLE = (
    "# Top\n\n"
    "Intro text.\n\n"
    "## Findings\n\n"
    "### Finding 1 - foo\n\n"
    "#### Description\n\nFoo desc.\n\n"
    "### Finding 2 - bar\n\n"
    "#### Description\n\nBar desc.\n"
)


class TestExtractSubtree:
    def test_extract_finding_1_returns_just_that_subtree(self):
        out = extract_subtree(SAMPLE, heading_level=3, title_match="Finding 1 - foo")
        # Heading 1 (rebased from level 3 to level 1):
        assert out.startswith("# Finding 1 - foo")
        # Description should be at level 2 (rebased from 4)
        assert "## Description" in out
        # Should not contain Finding 2 content
        assert "Finding 2" not in out

    def test_no_match_raises(self):
        with pytest.raises(MarkdownExtractionError, match="not found"):
            extract_subtree(SAMPLE, heading_level=3, title_match="Finding 99")

    def test_level_rebasing_is_correct(self):
        out = extract_subtree(SAMPLE, heading_level=3, title_match="Finding 2 - bar")
        # Original Finding 2 was at level 3; should now be level 1.
        assert out.startswith("# Finding 2 - bar")
        # Original Description was at level 4; should now be level 2.
        assert "## Description" in out


class TestExtractMultiMatch:
    def test_multiple_matches_raises(self):
        md = "# Top\n\n## Section\n\nfirst\n\n## Section\n\nsecond\n"
        with pytest.raises(MarkdownExtractionError, match="multiple"):
            extract_subtree(md, heading_level=2, title_match="Section")
