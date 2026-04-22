"""Tests for the markdown-it-py AST → BlockElement tree normalizer."""

from __future__ import annotations

from archetype.markdown._ast_normalizer import (
    NormalizedDocument,
    normalize,
)
from archetype.markdown.elements import (
    MarkdownBulletList,
    MarkdownCodeBlock,
    MarkdownHeading,
    MarkdownNumberedList,
    MarkdownTable,
)


class TestNormalizeHeadings:
    def test_single_h1_with_no_body(self):
        doc = normalize("# Hello\n")
        assert isinstance(doc, NormalizedDocument)
        assert doc.frontmatter is None
        assert len(doc.blocks) == 1
        h = doc.blocks[0]
        assert isinstance(h, MarkdownHeading)
        assert h.text == "Hello"
        assert h.body == []

    def test_h1_with_h2_inside_scope(self):
        doc = normalize("# Top\n\n## Inner\n")
        h1 = doc.blocks[0]
        assert isinstance(h1, MarkdownHeading)
        assert h1.text == "Top"
        assert len(h1.body) == 1
        assert isinstance(h1.body[0], MarkdownHeading)
        assert h1.body[0].text == "Inner"

    def test_two_sibling_h1_headings(self):
        doc = normalize("# A\n\n# B\n")
        assert len(doc.blocks) == 2
        assert all(isinstance(b, MarkdownHeading) for b in doc.blocks)
        assert doc.blocks[0].text == "A"
        assert doc.blocks[1].text == "B"


class TestNormalizeCodeBlock:
    def test_fenced_code_with_language(self):
        doc = normalize("# Top\n\n```python\nx = 1\n```\n")
        h = doc.blocks[0]
        assert len(h.body) == 1
        c = h.body[0]
        assert isinstance(c, MarkdownCodeBlock)
        assert c.language == "python"
        assert c.content == "x = 1\n"


class TestNormalizeLists:
    def test_bullet_list(self):
        doc = normalize("# Top\n\n- a\n- b\n")
        h = doc.blocks[0]
        assert len(h.body) == 1
        bl = h.body[0]
        assert isinstance(bl, MarkdownBulletList)
        assert bl.items == ["a", "b"]

    def test_numbered_list(self):
        doc = normalize("# Top\n\n1. a\n2. b\n")
        h = doc.blocks[0]
        nl = h.body[0]
        assert isinstance(nl, MarkdownNumberedList)
        assert nl.items == ["a", "b"]


class TestNormalizeTable:
    def test_gfm_table(self):
        md = "# Top\n\n| Path | Lines |\n|------|-------|\n| a.py | 12    |\n| b.py | 7     |\n"
        doc = normalize(md)
        h = doc.blocks[0]
        t = h.body[0]
        assert isinstance(t, MarkdownTable)
        assert t.columns == ["Path", "Lines"]
        assert len(t.rows) == 2
        assert t.rows[0].cells == ["a.py", "12"]


class TestNormalizeFrontmatter:
    def test_yaml_frontmatter(self):
        md = "---\nname: x\nversion: 1\n---\n\n# Top\n"
        doc = normalize(md)
        assert doc.frontmatter is not None
        assert doc.frontmatter.parsed == {"name": "x", "version": 1}
        assert "name: x" in doc.frontmatter.raw_yaml

    def test_frontmatter_syntax_below_top_is_ignored(self):
        """Frontmatter is recognized only at byte 0. `---\\nkey: val\\n---` content
        appearing under a heading is legitimate prose (e.g., docs about frontmatter,
        embedded markdown templates, ADR samples) and must NOT be extracted as the
        document's frontmatter. markdown-it parses such content as a thematic-break /
        paragraph / thematic-break sequence — none of which map to MarkdownFrontmatter.
        """
        md = (
            "# Top\n\n"
            "## Frontmatter Reference\n\n"
            "Posts begin with frontmatter:\n\n"
            "---\nfake: yaml\n---\n"
        )
        doc = normalize(md)
        assert doc.frontmatter is None


class TestNormalizeParagraph:
    """Paragraphs INSIDE a heading body must be captured as MarkdownParagraph
    elements. Without this, AsHeading body content is silently dropped."""

    def test_heading_with_paragraph_body(self):
        from archetype.markdown.elements import MarkdownParagraph

        doc = normalize("# Top\n\nThe body content here.\n")
        h = doc.blocks[0]
        assert isinstance(h, MarkdownHeading)
        assert len(h.body) == 1
        p = h.body[0]
        assert isinstance(p, MarkdownParagraph)
        assert p.content == "The body content here."

    def test_heading_with_two_paragraphs(self):
        from archetype.markdown.elements import MarkdownParagraph

        doc = normalize("# Top\n\nFirst paragraph.\n\nSecond paragraph.\n")
        h = doc.blocks[0]
        assert len(h.body) == 2
        assert isinstance(h.body[0], MarkdownParagraph)
        assert isinstance(h.body[1], MarkdownParagraph)
        assert h.body[0].content == "First paragraph."
        assert h.body[1].content == "Second paragraph."
