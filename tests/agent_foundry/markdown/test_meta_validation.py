"""Tests for class-definition-time meta-validation of template models."""

from __future__ import annotations

import pytest

from agent_foundry.markdown.errors import MarkdownTemplateError
from agent_foundry.markdown.template_model import MarkdownHeader


class TestTitleRule:
    """Every MarkdownHeader subclass must have title:str. Inherited by default;
    catches accidental override to a non-string type."""

    def test_subclass_inherits_title_passes(self):
        # No exception at class definition.
        class SimpleHeader(MarkdownHeader):
            pass

    def test_subclass_overrides_title_to_str_passes(self):
        from typing import Annotated

        from agent_foundry.markdown.annotations import TextTemplate

        class SimpleHeader(MarkdownHeader):
            title: Annotated[str, TextTemplate("X - {value}")]

    def test_subclass_overrides_title_to_non_str_raises(self):
        with pytest.raises(MarkdownTemplateError, match="title"):

            class BrokenHeader(MarkdownHeader):
                title: int  # type: ignore[assignment]

    def test_subclass_overrides_title_with_annotated_int_raises(self):
        """TextTemplate-annotated title is fine when underlying type is str;
        annotating a non-str type should still raise."""
        from typing import Annotated

        from agent_foundry.markdown.annotations import TextTemplate

        with pytest.raises(MarkdownTemplateError, match="title"):

            class BrokenHeader(MarkdownHeader):
                title: Annotated[int, TextTemplate("{value}")]  # type: ignore[arg-type]


class TestMetaValidationFiresWithFullFields:
    """The validator must see the subclass's body fields, not just inherited ones.
    This regression test pins the contract: __pydantic_init_subclass__ vs the
    earlier-firing __init_subclass__ make a real difference for our rules."""

    def test_subclass_body_fields_visible_in_validator(self):
        observed: dict = {}

        class Probe(MarkdownHeader):
            extra_field: str

        # MarkdownHeader.__pydantic_init_subclass__ fired when Probe was defined.
        # validate_template_class ran against Probe at that point (no error = fields
        # were visible). Confirm model_fields includes the body field as Pydantic saw it.
        observed["fields"] = list(Probe.model_fields.keys())

        # The hook fires at class definition; body field must be visible.
        assert "extra_field" in observed["fields"]
        assert "title" in observed["fields"]
