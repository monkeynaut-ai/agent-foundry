"""End-to-end integration test: real template model + instruction template
using all three forms, rendered via resolve, asserted against an
expected string."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from archetype.markdown.annotations import AsBulletList, AsHeading
from archetype.markdown.template_model import MarkdownDocument, MarkdownHeader
from archetype.templating import resolve

# ── A small feature-definition-like template model ──────────────────────


class _FrontMatter(BaseModel):
    slug: str


class _Assumptions(MarkdownHeader):
    title: str = "Assumptions"
    items: Annotated[list[str], AsBulletList()]


class _FeatureDef(MarkdownDocument):
    frontmatter: _FrontMatter | None = None
    title: str = Field(description="Feature name (renders as the top heading).")
    problem_statement: Annotated[str, AsHeading()] = Field(description="The current pain.")
    assumptions: _Assumptions = Field(description="Truth-claims the design rests on.")


# ── An instruction template using all three forms ────────────────────────


_TEMPLATE = """\
# Test

## Input shape

The feature definition has these sections:
{% for field in template_fields(_FeatureDef) %}
- **{{ field.heading }}** — {{ field.description }}
{% endfor %}

## This run

You are working on **{{ feature.title }}**.

Problem: {{ feature.problem_statement }}

Assumptions:
{% for item in feature.assumptions.items %}
- {{ item }}
{% endfor %}

## Output skeleton

{{ render_template(_FeatureDef) }}
"""


class TestRenderInstructionsIntegration:
    def test_full_render_against_populated_instance(self):
        feature = _FeatureDef(
            frontmatter=_FrontMatter(slug="auth"),
            title="Authentication",
            problem_statement="Users can't log in.",
            assumptions=_Assumptions(items=["Low traffic", "SSO available"]),
        )

        result = resolve(_TEMPLATE, feature=feature, _FeatureDef=_FeatureDef)

        # Structural iteration via template_fields() surfaces all three body fields
        # with their descriptions.
        assert "- **Problem Statement** — The current pain." in result
        assert "- **Assumptions** — Truth-claims the design rests on." in result

        # Scalar substitution and nested list iteration work on the
        # populated instance.
        assert "You are working on **Authentication**." in result
        assert "Problem: Users can't log in." in result
        assert "- Low traffic\n- SSO available" in result

        # Skeleton renderer produces body-heading structure. (Phase 1's
        # render_template emits placeholder comments for unfilled slots; we
        # just assert the body headings we annotated appear.)
        assert "## Problem Statement" in result
        assert "## Output skeleton" in result
