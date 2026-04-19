"""Tests for the element-tree → domain-instance projector."""

from __future__ import annotations

import pytest

from agent_foundry.markdown._ast_normalizer import normalize
from agent_foundry.markdown._projector import project_to_model
from agent_foundry.markdown.errors import MarkdownValidationError
from tests.agent_foundry.markdown.fixtures.sample_models import (
    HeaderWithSummary,
    SimpleHeader,
)


class TestProjectToModelSimple:
    def test_simple_header_with_only_title(self):
        doc = normalize("# Hello\n")
        instance = project_to_model(doc, SimpleHeader)
        assert instance.title == "Hello"

    def test_header_with_summary_extracts_str_body(self):
        doc = normalize("# My Doc\n\n## Summary\n\nGood work.\n")
        instance = project_to_model(doc, HeaderWithSummary)
        assert instance.title == "My Doc"
        assert "Good work." in instance.summary


class TestProjectorStrictOrder:
    def test_missing_required_heading_raises(self):
        from tests.agent_foundry.markdown.fixtures.sample_models import HeaderWithSummary

        doc = normalize("# Top\n\nSome text but no Summary heading.\n")
        with pytest.raises(MarkdownValidationError, match="Summary"):
            project_to_model(doc, HeaderWithSummary)


class TestProjectorPassthrough:
    def test_extra_unmodeled_heading_is_skipped(self):
        from tests.agent_foundry.markdown.fixtures.sample_models import HeaderWithSummary

        doc = normalize("# Top\n\n## Notes\n\nThis is a note.\n\n## Summary\n\nThe real summary.\n")
        instance = project_to_model(doc, HeaderWithSummary)
        assert "real summary" in instance.summary
