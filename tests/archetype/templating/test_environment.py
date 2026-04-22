"""Tests for the Jinja environment factory."""

from __future__ import annotations

from typing import Annotated

import jinja2
from pydantic import Field

from archetype.markdown.annotations import AsHeading
from archetype.markdown.template_model import MarkdownHeader
from archetype.templating.environment import build_environment


class TestEnvironmentConfig:
    """The factory returns a Jinja2 Environment preconfigured for
    markdown-instruction templates."""

    def test_returns_jinja2_environment(self):
        env = build_environment()
        assert isinstance(env, jinja2.Environment)

    def test_trim_blocks_enabled(self):
        env = build_environment()
        assert env.trim_blocks is True

    def test_lstrip_blocks_enabled(self):
        env = build_environment()
        assert env.lstrip_blocks is True

    def test_autoescape_disabled(self):
        env = build_environment()
        # autoescape may be the literal False or a callable that returns False.
        if callable(env.autoescape):
            assert env.autoescape("anything.md") is False
        else:
            assert env.autoescape is False


class TestEnvironmentGlobals:
    """The factory registers `template` and `render_template` as Jinja globals
    so instruction templates can call them directly."""

    def test_template_fields_global_registered(self):
        env = build_environment()
        assert "template_fields" in env.globals

    def test_render_template_global_registered(self):
        env = build_environment()
        assert "render_template" in env.globals


class TestEnvironmentGlobalsUsable:
    """The registered globals work when invoked from inside a Jinja template."""

    def test_template_global_iterates_inside_jinja(self):
        class Doc(MarkdownHeader):
            summary: Annotated[str, AsHeading()] = Field(description="Summary text.")
            detail: Annotated[str, AsHeading()] = Field(description="Detail text.")

        env = build_environment()
        tmpl = env.from_string(
            "{% for field in template_fields(Doc) %}{{ field.heading }}|{% endfor %}"
        )
        result = tmpl.render(Doc=Doc)

        assert result == "Summary|Detail|"

    def test_render_template_global_returns_skeleton_inside_jinja(self):
        class Doc(MarkdownHeader):
            summary: Annotated[str, AsHeading()] = Field(description="Summary.")

        env = build_environment()
        tmpl = env.from_string("{{ render_template(Doc) }}")
        result = tmpl.render(Doc=Doc)

        # Phase 1's render_template produces a skeleton containing the title
        # heading and section headings. We just assert the section heading
        # appears in the output — the full shape is covered by Phase 1 tests.
        assert "Summary" in result
