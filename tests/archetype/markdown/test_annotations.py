"""Tests for annotation dataclasses."""

from __future__ import annotations

import dataclasses

import pytest

from archetype.markdown.annotations import (
    AsBulletList,
    AsCodeBlock,
    AsHeading,
    AsNumberedList,
    AsTable,
    TextTemplate,
)


class TestAnnotationConstruction:
    """Each annotation is a frozen dataclass; constructable with valid args."""

    def test_as_heading_takes_no_args(self):
        h = AsHeading()
        assert h is not None

    def test_as_code_block_with_language(self):
        c = AsCodeBlock(language="python")
        assert c.language == "python"

    def test_as_code_block_without_language(self):
        c = AsCodeBlock()
        assert c.language is None

    def test_as_table_takes_no_args(self):
        AsTable()

    def test_as_bullet_list_takes_no_args(self):
        AsBulletList()

    def test_as_numbered_list_takes_no_args(self):
        AsNumberedList()

    def test_text_template_takes_template_string(self):
        t = TextTemplate("Finding {ordinal} - {value}")
        assert t.template == "Finding {ordinal} - {value}"

    def test_text_template_requires_template(self):
        with pytest.raises(TypeError):
            TextTemplate()  # type: ignore[call-arg]


class TestAnnotationImmutability:
    """All annotations are frozen dataclasses; instances are immutable and hashable."""

    def test_as_heading_is_hashable(self):
        hash(AsHeading())

    def test_text_template_equal_for_equal_template(self):
        a = TextTemplate("X")
        b = TextTemplate("X")
        assert a == b
        assert hash(a) == hash(b)

    def test_as_code_block_immutable(self):
        c = AsCodeBlock(language="python")
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.language = "rust"  # type: ignore[misc]
