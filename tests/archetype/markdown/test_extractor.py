"""Tests for the subtree extractor."""

from __future__ import annotations

import pytest

from archetype.markdown.errors import MarkdownExtractionError
from archetype.markdown.extractor import extract_subtree

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


class TestExtractAndValidate:
    """End-to-end: extract a Finding subtree from a Reviewer document and
    validate it against the Finding model."""

    def test_extract_finding_then_validate(self):
        from archetype.markdown.parser import validate_markdown
        from tests.archetype.markdown.fixtures.sample_models import Finding

        md = (
            "# Review\n\n"
            "## Findings\n\n"
            "### Finding 1 - missing tests\n\n"
            "```python\nx = 1\n```\n\n"
            "- t1\n- t2\n\n"
            "#### Description\n\nNo tests.\n\n"
            "#### Rationale\n\nTDD is required.\n\n"
            "### Finding 2 - other\n\n"
            "```python\ny = 2\n```\n\n"
            "- t3\n\n"
            "#### Description\n\nOther.\n\n"
            "#### Rationale\n\nOther reason.\n"
        )
        fragment = extract_subtree(md, heading_level=3, title_match="Finding 1 - missing tests")
        finding = validate_markdown(fragment, Finding)
        assert finding.title == "missing tests"
        assert finding.code.strip() == "x = 1"
        assert finding.tags == ["t1", "t2"]
        assert "No tests" in finding.description


class TestExtractSubtreePreservesContent:
    def test_extract_preserves_table_in_subtree(self):
        md = (
            "# Top\n\n"
            "## Section With Table\n\n"
            "| Path | Lines |\n"
            "|------|-------|\n"
            "| a.py | 12    |\n"
            "| b.py | 7     |\n"
        )
        out = extract_subtree(md, heading_level=2, title_match="Section With Table")
        assert "| Path | Lines |" in out
        assert "| a.py | 12 |" in out
        assert "| b.py | 7 |" in out
