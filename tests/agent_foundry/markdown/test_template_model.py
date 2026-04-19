"""Tests for MarkdownHeader and MarkdownDocument base classes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_foundry.markdown.template_model import MarkdownHeader


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
