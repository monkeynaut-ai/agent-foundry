"""Tests for MarkdownHeader and MarkdownDocument base classes."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from archetype.markdown.template_model import MarkdownDocument, MarkdownHeader


class TestMarkdownHeaderTitle:
    """MarkdownHeader requires a title field on every subclass."""

    def test_given_title_when_constructed_then_title_set(self):
        class SimpleHeader(MarkdownHeader):
            pass

        h = SimpleHeader(title="My Heading")
        assert h.title == "My Heading"

    def test_missing_title_raises_validation_error(self):
        class SimpleHeader(MarkdownHeader):
            pass

        with pytest.raises(ValidationError, match="title"):
            SimpleHeader()  # type: ignore[call-arg]

    def test_subclass_can_have_additional_fields(self):
        class WithBody(MarkdownHeader):
            description: str

        w = WithBody(title="X", description="Y")
        assert w.title == "X"
        assert w.description == "Y"


class FrontmatterSchema(BaseModel):
    name: str
    version: int


class TestMarkdownDocument:
    """MarkdownDocument extends MarkdownHeader with an optional frontmatter field."""

    def test_inherits_title_from_markdown_header(self):
        class Doc(MarkdownDocument):
            pass

        d = Doc(title="hello")
        assert d.title == "hello"
        assert d.frontmatter is None

    def test_subclass_can_override_frontmatter_type(self):
        class Doc(MarkdownDocument):
            frontmatter: FrontmatterSchema | None = None

        d = Doc(title="hello", frontmatter=FrontmatterSchema(name="x", version=1))
        assert d.frontmatter is not None
        assert d.frontmatter.name == "x"

    def test_frontmatter_optional_default_none(self):
        class Doc(MarkdownDocument):
            frontmatter: FrontmatterSchema | None = None

        d = Doc(title="hello")
        assert d.frontmatter is None

    def test_markdown_document_is_markdown_header(self):
        assert issubclass(MarkdownDocument, MarkdownHeader)
