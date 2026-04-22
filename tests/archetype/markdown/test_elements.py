"""Tests for markdown element classes (parser intermediate representation)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from archetype.markdown.elements import (
    MarkdownBulletList,
    MarkdownCodeBlock,
    MarkdownFrontmatter,
    MarkdownHeading,
    MarkdownKind,
    MarkdownNumberedList,
    MarkdownParagraph,
    MarkdownTable,
    MarkdownTableRow,
)


class TestMarkdownHeading:
    """MarkdownHeading represents a parsed markdown heading + its scope body."""

    def test_given_text_when_constructed_then_kind_is_heading(self):
        h = MarkdownHeading(text="Goal", body=[])
        assert h.kind == MarkdownKind.HEADING
        assert h.text == "Goal"
        assert h.body == []

    def test_given_no_body_when_constructed_then_body_defaults_to_empty(self):
        h = MarkdownHeading(text="Goal")
        assert h.body == []

    def test_kind_is_immutable_discriminator(self):
        """The kind field cannot be set to a non-HEADING value."""
        with pytest.raises(ValidationError):
            MarkdownHeading(kind="not_a_heading", text="Goal")  # type: ignore[arg-type]


class TestMarkdownCodeBlock:
    """MarkdownCodeBlock represents a fenced code block."""

    def test_given_language_and_content_when_constructed_then_fields_match(self):
        c = MarkdownCodeBlock(language="python", content="def foo(): pass")
        assert c.kind == MarkdownKind.CODE_BLOCK
        assert c.language == "python"
        assert c.content == "def foo(): pass"

    def test_given_no_language_when_constructed_then_language_is_none(self):
        c = MarkdownCodeBlock(content="raw text")
        assert c.language is None


class TestMarkdownTable:
    """MarkdownTable represents a GFM-style markdown table."""

    def test_given_columns_and_rows_when_constructed_then_fields_match(self):
        t = MarkdownTable(
            columns=["Path", "Lines"],
            rows=[
                MarkdownTableRow(cells=["src/foo.py", "120"]),
                MarkdownTableRow(cells=["src/bar.py", "45"]),
            ],
        )
        assert t.kind == MarkdownKind.TABLE
        assert t.columns == ["Path", "Lines"]
        assert len(t.rows) == 2
        assert t.rows[0].cells == ["src/foo.py", "120"]

    def test_given_zero_rows_when_constructed_then_rows_is_empty(self):
        t = MarkdownTable(columns=["A", "B"], rows=[])
        assert t.rows == []


class TestMarkdownBulletList:
    def test_given_items_when_constructed_then_fields_match(self):
        bl = MarkdownBulletList(items=["alpha", "beta"])
        assert bl.kind == MarkdownKind.BULLET_LIST
        assert bl.items == ["alpha", "beta"]


class TestMarkdownNumberedList:
    def test_given_items_when_constructed_then_fields_match(self):
        nl = MarkdownNumberedList(items=["first", "second"])
        assert nl.kind == MarkdownKind.NUMBERED_LIST
        assert nl.items == ["first", "second"]


class TestMarkdownFrontmatter:
    """Frontmatter is a document-root-only element; not part of BlockElement."""

    def test_given_raw_yaml_when_constructed_then_fields_match(self):
        fm = MarkdownFrontmatter(raw_yaml="key: value\n", parsed={"key": "value"})
        assert fm.kind == MarkdownKind.FRONTMATTER
        assert fm.raw_yaml == "key: value\n"
        assert fm.parsed == {"key": "value"}

    def test_frontmatter_not_in_block_element_union(self):
        """Frontmatter cannot appear inside a heading body."""
        from typing import get_args

        from archetype.markdown.elements import BlockElement

        union_args = get_args(get_args(BlockElement)[0])
        assert MarkdownFrontmatter not in union_args


class TestMarkdownParagraph:
    """MarkdownParagraph captures a single paragraph of inline text. Internal
    AST representation; not addressable via any annotation."""

    def test_given_content_when_constructed_then_fields_match(self):
        p = MarkdownParagraph(content="Some prose.")
        assert p.kind == MarkdownKind.PARAGRAPH
        assert p.content == "Some prose."
