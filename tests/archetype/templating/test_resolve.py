"""Tests for the resolve() helper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import jinja2
import pytest
from pydantic import Field

from archetype.markdown.annotations import AsHeading
from archetype.markdown.template_model import MarkdownHeader
from archetype.templating.resolve import resolve


@dataclass
class _Feature:
    """Minimal context object for the tests (not a Pydantic model)."""

    name: str
    items: list[str]


class TestScalarSubstitution:
    def test_substitutes_scalar_attribute(self):
        ctx = _Feature(name="Auth", items=[])
        result = resolve("Feature: {{ feature.name }}", feature=ctx)
        assert result == "Feature: Auth"


class TestListIteration:
    def test_iterates_list_attribute(self):
        ctx = _Feature(name="X", items=["a", "b", "c"])
        template_text = "{% for item in feature.items %}- {{ item }}\n{% endfor %}"
        result = resolve(template_text, feature=ctx)
        assert result == "- a\n- b\n- c\n"


class TestStructuralIteration:
    """Instruction templates iterate `template_fields(ModelClass)` to emit a prose
    list of section headings and descriptions."""

    def test_template_global_produces_heading_list(self):
        class Doc(MarkdownHeader):
            summary: Annotated[str, AsHeading()] = Field(description="Summary.")
            detail: Annotated[str, AsHeading()] = Field(description="Detail.")

        template_text = (
            "{% for field in template_fields(Doc) %}"
            "- **{{ field.heading }}** — {{ field.description }}\n"
            "{% endfor %}"
        )
        result = resolve(template_text, Doc=Doc)

        assert result == "- **Summary** — Summary.\n- **Detail** — Detail.\n"


class TestSkeletonRendering:
    """render_template() used as a Jinja global emits the Phase 1 skeleton."""

    def test_render_template_skeleton_matches_direct_call(self):
        from archetype.markdown.renderer import render_template

        class Doc(MarkdownHeader):
            summary: Annotated[str, AsHeading()] = Field(description="Summary.")

        direct = render_template(Doc)
        via_jinja = resolve("{{ render_template(Doc) }}", Doc=Doc)

        assert via_jinja == direct


class TestMissingPath:
    """Undefined variables raise at render time — fail fast, don't silently
    insert empty strings."""

    def test_missing_variable_raises(self):
        with pytest.raises(jinja2.UndefinedError):
            resolve("{{ missing.value }}")

    def test_missing_attribute_raises(self):
        ctx = _Feature(name="X", items=[])
        with pytest.raises(jinja2.UndefinedError):
            resolve("{{ feature.nonexistent }}", feature=ctx)


class TestWhitespaceBehavior:
    """trim_blocks and lstrip_blocks together mean block tags on their own
    lines don't leave stray blank lines in the output."""

    def test_block_tags_do_not_leave_blank_lines(self):
        ctx = _Feature(name="X", items=["a", "b"])
        template_text = "Start\n{% for item in feature.items %}\n- {{ item }}\n{% endfor %}\nEnd\n"
        result = resolve(template_text, feature=ctx)

        # No extra blank lines between list items or around the block.
        assert result == "Start\n- a\n- b\nEnd\n"
