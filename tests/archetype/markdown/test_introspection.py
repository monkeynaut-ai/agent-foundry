"""Tests for the template_fields() accessor — heading-field metadata extraction."""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from archetype.markdown.annotations import AsBulletList, AsCodeBlock, AsHeading
from archetype.markdown.introspection import FieldInfo, template_fields
from archetype.markdown.template_model import MarkdownDocument, MarkdownHeader


class TestTemplateOnAsHeadingFields:
    """For AsHeading-annotated str body fields, template_fields() returns heading
    derived from the field name (snake_case → Title Case) plus the field's
    Pydantic description."""

    def test_single_as_heading_field_returns_one_field_info(self):
        class Doc(MarkdownHeader):
            summary: Annotated[str, AsHeading()] = Field(description="A short summary.")

        result = template_fields(Doc)

        assert len(result) == 1
        assert isinstance(result[0], FieldInfo)

    def test_heading_is_title_case_from_field_name(self):
        class Doc(MarkdownHeader):
            problem_statement: Annotated[str, AsHeading()] = Field(description="The problem.")

        (info,) = template_fields(Doc)

        # snake_to_title capitalizes each word (matching Phase 1's renderer convention).
        assert info.heading == "Problem Statement"

    def test_description_comes_from_field_description(self):
        class Doc(MarkdownHeader):
            summary: Annotated[str, AsHeading()] = Field(description="A one-liner.")

        (info,) = template_fields(Doc)

        assert info.description == "A one-liner."

    def test_missing_description_yields_none(self):
        class Doc(MarkdownHeader):
            summary: Annotated[str, AsHeading()]

        (info,) = template_fields(Doc)

        assert info.description is None

    def test_multiple_fields_in_declaration_order(self):
        class Doc(MarkdownHeader):
            first: Annotated[str, AsHeading()] = Field(description="First section.")
            second: Annotated[str, AsHeading()] = Field(description="Second section.")
            third: Annotated[str, AsHeading()] = Field(description="Third section.")

        result = template_fields(Doc)

        assert [f.heading for f in result] == ["First", "Second", "Third"]


class TestTemplateOnNestedMarkdownHeader:
    """For body fields typed as a MarkdownHeader subclass, template_fields() uses
    the subclass's `title` field default as the heading text."""

    def test_nested_header_uses_subclass_title_default(self):
        class NestedSection(MarkdownHeader):
            title: str = "Desired outcomes"
            inner: Annotated[str, AsHeading()] = Field(description="Inner body.")

        class Doc(MarkdownHeader):
            section: NestedSection = Field(description="A nested section.")

        (info,) = template_fields(Doc)

        assert info.heading == "Desired outcomes"
        assert info.description == "A nested section."

    def test_nested_header_without_title_default_raises(self):
        """If the nested MarkdownHeader subclass lacks a title default,
        template_fields() cannot derive a heading — raises ValueError."""

        class NestedSection(MarkdownHeader):
            inner: Annotated[str, AsHeading()]

        class Doc(MarkdownHeader):
            section: NestedSection = Field(description="...")

        with pytest.raises(ValueError, match="section"):
            template_fields(Doc)


class TestTemplateSkipsStructuralFields:
    """template_fields() must skip 'title' and 'frontmatter' — they are the document's
    structural heading and metadata, not body sections."""

    def test_title_is_skipped(self):
        class Doc(MarkdownHeader):
            summary: Annotated[str, AsHeading()] = Field(description="Summary.")

        result = template_fields(Doc)

        # Only 'summary' should appear; 'title' (inherited from MarkdownHeader) is skipped.
        assert len(result) == 1
        assert result[0].heading == "Summary"

    def test_frontmatter_is_skipped(self):
        class FM(BaseModel):
            slug: str

        class Doc(MarkdownDocument):
            frontmatter: FM | None = None
            summary: Annotated[str, AsHeading()] = Field(description="Summary.")

        result = template_fields(Doc)

        headings = [f.heading for f in result]
        assert "Frontmatter" not in headings
        assert headings == ["Summary"]


class TestTemplateUnsupportedShapes:
    """Fields that template_fields() does not know how to describe as sections must
    raise a clear ValueError — so Slice 1's scope is visible and future
    extensions are deliberate."""

    def test_as_bullet_list_top_level_raises(self):
        """AsBulletList is a non-heading body field — not a section, not
        supported by template_fields() in Slice 1."""

        class Doc(MarkdownHeader):
            items: Annotated[list[str], AsBulletList()] = Field(description="Items.")

        with pytest.raises(ValueError, match="items"):
            template_fields(Doc)

    def test_as_code_block_top_level_raises(self):
        class Doc(MarkdownHeader):
            snippet: Annotated[str, AsCodeBlock()] = Field(description="Code.")

        with pytest.raises(ValueError, match="snippet"):
            template_fields(Doc)

    def test_untyped_body_field_raises(self):
        """A body field with neither a role annotation nor a MarkdownHeader type
        is ambiguous — template_fields() raises."""

        class Doc(MarkdownHeader):
            raw: str = Field(description="Raw text.")

        with pytest.raises(ValueError, match="raw"):
            template_fields(Doc)


class TestTemplateOnMarkdownDocumentSubclass:
    """template_fields() works on MarkdownDocument subclasses too — same semantics
    as MarkdownHeader, with the inherited frontmatter field also skipped."""

    def test_markdown_document_frontmatter_and_title_skipped(self):
        class FM(BaseModel):
            slug: str

        class Doc(MarkdownDocument):
            frontmatter: FM | None = None
            summary: Annotated[str, AsHeading()] = Field(description="Summary.")
            detail: Annotated[str, AsHeading()] = Field(description="Detail.")

        result = template_fields(Doc)

        assert [f.heading for f in result] == ["Summary", "Detail"]


class TestFieldInfoShape:
    """FieldInfo is a frozen dataclass with heading and description attributes."""

    def test_field_info_is_hashable_and_immutable(self):
        fi = FieldInfo(heading="X", description="Y")

        # Hashable — usable as a dict key or set member.
        _ = {fi}

        # Frozen — attributes can't be reassigned.
        with pytest.raises((AttributeError, Exception)):
            fi.heading = "Z"  # type: ignore[misc]

    def test_field_info_equality_by_value(self):
        assert FieldInfo(heading="X", description="Y") == FieldInfo(heading="X", description="Y")

    def test_field_info_description_may_be_none(self):
        fi = FieldInfo(heading="X", description=None)
        assert fi.description is None
