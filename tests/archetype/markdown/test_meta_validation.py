"""Tests for class-definition-time meta-validation of template models."""

from __future__ import annotations

from typing import Annotated

import pytest

from archetype.markdown.annotations import (
    AsBulletList,
    AsCodeBlock,
    AsHeading,
    AsTable,
)
from archetype.markdown.errors import MarkdownTemplateError
from archetype.markdown.template_model import MarkdownHeader


class TestTitleRule:
    """Every MarkdownHeader subclass must have title:str. Inherited by default;
    catches accidental override to a non-string type."""

    def test_subclass_inherits_title_passes(self):
        # No exception at class definition.
        class SimpleHeader(MarkdownHeader):
            pass

    def test_subclass_overrides_title_to_str_passes(self):
        from archetype.markdown.annotations import TextTemplate

        class SimpleHeader(MarkdownHeader):
            title: Annotated[str, TextTemplate("X - {value}")]

    def test_subclass_overrides_title_to_non_str_raises(self):
        with pytest.raises(MarkdownTemplateError, match="title"):

            class BrokenHeader(MarkdownHeader):
                title: int  # type: ignore[assignment]

    def test_subclass_overrides_title_with_annotated_int_raises(self):
        """TextTemplate-annotated title is fine when underlying type is str;
        annotating a non-str type should still raise."""
        from archetype.markdown.annotations import TextTemplate

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


class TestBodyOrderRule:
    """Within a MarkdownHeader's body, non-heading fields must precede heading
    fields. Title is exempt (always the container heading); frontmatter is exempt
    (always rendered at top)."""

    def test_only_non_heading_body_fields_passes(self):
        class OkA(MarkdownHeader):
            code: Annotated[str, AsCodeBlock()]
            tags: Annotated[list[str], AsBulletList()]

    def test_only_heading_body_fields_passes(self):
        class OkB(MarkdownHeader):
            description: Annotated[str, AsHeading()]
            rationale: Annotated[str, AsHeading()]

    def test_non_heading_then_heading_passes(self):
        class OkC(MarkdownHeader):
            code: Annotated[str, AsCodeBlock()]
            description: Annotated[str, AsHeading()]

    def test_heading_then_non_heading_raises(self):
        with pytest.raises(MarkdownTemplateError, match="non-heading"):

            class Bad(MarkdownHeader):
                description: Annotated[str, AsHeading()]
                code: Annotated[str, AsCodeBlock()]

    def test_heading_then_table_raises(self):
        from pydantic import BaseModel

        class Row(BaseModel):
            a: str
            b: str

        with pytest.raises(MarkdownTemplateError, match="non-heading"):

            class Bad(MarkdownHeader):
                description: Annotated[str, AsHeading()]
                table: Annotated[list[Row], AsTable()]


class TestFrontmatterRule:
    """Frontmatter is allowed only on MarkdownDocument subclasses, only as the
    first declared field, and only with type BaseModel | None."""

    def test_frontmatter_on_markdown_document_passes(self):
        from pydantic import BaseModel

        from archetype.markdown.template_model import MarkdownDocument

        class FmSchema(BaseModel):
            x: int

        class Doc(MarkdownDocument):
            frontmatter: FmSchema | None = None

    def test_frontmatter_on_markdown_header_raises(self):
        from pydantic import BaseModel

        class FmSchema(BaseModel):
            x: int

        with pytest.raises(MarkdownTemplateError, match="frontmatter"):

            class BadHdr(MarkdownHeader):
                frontmatter: FmSchema | None = None  # not allowed: not a MarkdownDocument

    def test_frontmatter_not_first_field_raises(self):
        from pydantic import BaseModel

        from archetype.markdown.template_model import MarkdownDocument

        class FmSchema(BaseModel):
            x: int

        with pytest.raises(MarkdownTemplateError, match="first"):

            class BadDoc(MarkdownDocument):
                summary: Annotated[str, AsHeading()]  # before frontmatter — bad
                frontmatter: FmSchema | None = None

    def test_frontmatter_non_optional_raises(self):
        from pydantic import BaseModel

        from archetype.markdown.template_model import MarkdownDocument

        class FmSchema(BaseModel):
            x: int

        with pytest.raises(MarkdownTemplateError, match="frontmatter"):

            class BadDoc(MarkdownDocument):
                frontmatter: FmSchema  # missing | None — required type union


class TestTypeCompatibilityRule:
    """Each annotation has an allowed underlying type. Mismatches raise."""

    def test_as_heading_on_str_passes(self):
        class OkA(MarkdownHeader):
            description: Annotated[str, AsHeading()]

    def test_as_heading_on_int_raises(self):
        with pytest.raises(MarkdownTemplateError, match="AsHeading"):

            class BadA(MarkdownHeader):
                description: Annotated[int, AsHeading()]  # type: ignore[arg-type]

    def test_as_code_block_on_str_passes(self):
        class OkB(MarkdownHeader):
            code: Annotated[str, AsCodeBlock(language="python")]

    def test_as_code_block_on_int_raises(self):
        with pytest.raises(MarkdownTemplateError, match="AsCodeBlock"):

            class BadB(MarkdownHeader):
                code: Annotated[int, AsCodeBlock()]  # type: ignore[arg-type]

    def test_as_bullet_list_on_list_str_passes(self):
        class OkC(MarkdownHeader):
            tags: Annotated[list[str], AsBulletList()]

    def test_as_bullet_list_on_list_int_raises(self):
        with pytest.raises(MarkdownTemplateError, match="AsBulletList"):

            class BadC(MarkdownHeader):
                tags: Annotated[list[int], AsBulletList()]  # type: ignore[arg-type]

    def test_as_table_on_list_basemodel_passes(self):
        from pydantic import BaseModel

        class Row(BaseModel):
            a: str
            b: int

        class OkD(MarkdownHeader):
            rows: Annotated[list[Row], AsTable()]

    def test_as_table_on_list_str_raises(self):
        with pytest.raises(MarkdownTemplateError, match="AsTable"):

            class BadD(MarkdownHeader):
                rows: Annotated[list[str], AsTable()]  # type: ignore[arg-type]


class TestTextTemplateCompatibility:
    """TextTemplate has two valid contexts: MarkdownHeader.title (str) and
    list[MarkdownHeader-subclass] wrapper. All other uses raise."""

    def test_text_template_on_title_passes(self):
        from archetype.markdown.annotations import TextTemplate

        class WithTemplate(MarkdownHeader):
            title: Annotated[str, TextTemplate("Section {value}")]

    def test_text_template_on_list_of_markdown_header_passes(self):
        from archetype.markdown.annotations import TextTemplate

        class Item(MarkdownHeader):
            pass

        class HasItems(MarkdownHeader):
            items: Annotated[list[Item], TextTemplate("Custom Wrapper")]

    def test_text_template_on_str_body_field_raises(self):
        from archetype.markdown.annotations import TextTemplate

        with pytest.raises(MarkdownTemplateError, match="TextTemplate"):

            class Bad(MarkdownHeader):
                description: Annotated[str, TextTemplate("Section {value}")]

    def test_text_template_on_list_str_raises(self):
        from archetype.markdown.annotations import TextTemplate

        with pytest.raises(MarkdownTemplateError, match="TextTemplate"):

            class Bad(MarkdownHeader):
                tags: Annotated[list[str], TextTemplate("X")]


class TestBodyOrderRuleListOfHeader:
    """list[MarkdownHeader-subclass] is heading-introducing; non-heading after it raises."""

    def test_non_heading_after_list_of_header_raises(self):
        class Item(MarkdownHeader):
            pass

        with pytest.raises(MarkdownTemplateError, match="non-heading"):

            class Bad(MarkdownHeader):
                items: list[Item]  # heading-introducing
                code: Annotated[str, AsCodeBlock()]  # non-heading after

    def test_non_heading_after_single_header_raises(self):
        class Sub(MarkdownHeader):
            pass

        with pytest.raises(MarkdownTemplateError, match="non-heading"):

            class Bad(MarkdownHeader):
                child: Sub  # heading-introducing
                code: Annotated[str, AsCodeBlock()]  # non-heading after
