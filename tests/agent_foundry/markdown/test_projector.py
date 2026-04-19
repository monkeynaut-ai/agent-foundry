"""Tests for the element-tree → domain-instance projector."""

from __future__ import annotations

from agent_foundry.markdown._ast_normalizer import normalize
from agent_foundry.markdown._projector import project_to_model
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
