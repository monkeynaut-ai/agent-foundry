"""Tests for the markdown machinery error hierarchy."""

from __future__ import annotations

import pytest

from archetype.markdown.errors import (
    MarkdownError,
    MarkdownExtractionError,
    MarkdownTemplateError,
    MarkdownValidationError,
)


class TestErrorHierarchy:
    """All markdown errors share a common base class for catch-all handling."""

    def test_template_error_is_markdown_error(self):
        with pytest.raises(MarkdownError):
            raise MarkdownTemplateError("template broke")

    def test_validation_error_is_markdown_error(self):
        with pytest.raises(MarkdownError):
            raise MarkdownValidationError("validation broke")

    def test_extraction_error_is_markdown_error(self):
        with pytest.raises(MarkdownError):
            raise MarkdownExtractionError("extraction broke")

    def test_template_error_is_type_error(self):
        """MarkdownTemplateError fires at class definition; behaves as a TypeError."""
        assert issubclass(MarkdownTemplateError, TypeError)


class TestErrorMessages:
    """Error messages preserve their content."""

    def test_template_error_preserves_message(self):
        err = MarkdownTemplateError("field X is invalid")
        assert "field X is invalid" in str(err)

    def test_validation_error_preserves_message(self):
        err = MarkdownValidationError("expected ## Goal, found ## Goals")
        assert "expected ## Goal" in str(err)
