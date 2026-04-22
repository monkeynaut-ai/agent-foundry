"""Tests for the element-tree → domain-instance projector."""

from __future__ import annotations

import pytest

from archetype.markdown._ast_normalizer import normalize
from archetype.markdown._projector import project_to_model
from archetype.markdown.errors import MarkdownValidationError
from tests.archetype.markdown.fixtures.sample_models import (
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
        from tests.archetype.markdown.fixtures.sample_models import HeaderWithSummary

        doc = normalize("# Top\n\nSome text but no Summary heading.\n")
        with pytest.raises(MarkdownValidationError, match="Summary"):
            project_to_model(doc, HeaderWithSummary)


class TestProjectorPassthrough:
    def test_extra_unmodeled_heading_is_skipped(self):
        from tests.archetype.markdown.fixtures.sample_models import HeaderWithSummary

        doc = normalize("# Top\n\n## Notes\n\nThis is a note.\n\n## Summary\n\nThe real summary.\n")
        instance = project_to_model(doc, HeaderWithSummary)
        assert "real summary" in instance.summary


class TestProjectorHeadingCase:
    """Heading matching is case-insensitive.

    Authors routinely write sentence-case headings while the model's
    ``snake_to_title`` default produces Title Case. Both parse; the
    source casing is preserved on the resulting instance.
    """

    def test_given_lowercase_heading_when_projected_then_matches_title_case_field(self):
        doc = normalize("# Top\n\n## summary\n\nBody.\n")
        instance = project_to_model(doc, HeaderWithSummary)
        assert "Body." in instance.summary

    def test_given_sentence_case_heading_when_projected_then_matches_title_case_field(self):
        # 'Summary' (Title Case, single-word) is also sentence case — use a
        # multi-word heading variant in the fixture to exercise the real case.
        # HeaderWithSummary has only 'summary', so match against 'SUMMARY'
        # uppercase to prove case-folding.
        doc = normalize("# Top\n\n## SUMMARY\n\nBody.\n")
        instance = project_to_model(doc, HeaderWithSummary)
        assert "Body." in instance.summary

    def test_given_mixed_case_heading_when_projected_then_matches_title_case_field(self):
        doc = normalize("# Top\n\n## SuMmArY\n\nBody.\n")
        instance = project_to_model(doc, HeaderWithSummary)
        assert "Body." in instance.summary

    def test_given_non_matching_heading_when_projected_then_raises(self):
        # Guard: case-insensitive doesn't mean content-insensitive.
        doc = normalize("# Top\n\n## Notes\n\nBody.\n")
        with pytest.raises(MarkdownValidationError, match="Summary"):
            project_to_model(doc, HeaderWithSummary)
