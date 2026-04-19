"""Tests for markdown element classes (parser intermediate representation)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_foundry.markdown.elements import MarkdownHeading, MarkdownKind


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
