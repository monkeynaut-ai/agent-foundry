"""Reusable test models for the markdown machinery test suite."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from archetype.markdown.annotations import (
    AsBulletList,
    AsCodeBlock,
    AsHeading,
    AsNumberedList,
    TextTemplate,
)
from archetype.markdown.template_model import MarkdownDocument, MarkdownHeader


class SimpleHeader(MarkdownHeader):
    """The smallest possible MarkdownHeader subclass — just a title."""


class HeaderWithSummary(MarkdownHeader):
    """A header with one labeled-section body field."""

    summary: Annotated[str, AsHeading()]


class FindingMetadata(BaseModel):
    sha: str
    severity: str


class Finding(MarkdownHeader):
    """A finding: title with ordinal-prefix template, then body sections."""

    title: Annotated[str, TextTemplate("Finding {ordinal} - {value}")]
    code: Annotated[str, AsCodeBlock(language="python")]
    tags: Annotated[list[str], AsBulletList()]
    description: Annotated[str, AsHeading()]
    rationale: Annotated[str, AsHeading()]


class ReviewerMetadata(BaseModel):
    change_set_name: str
    commit_range: str


class ReviewerOutput(MarkdownDocument):
    """The full Reviewer template — exercises every Phase-1 annotation."""

    frontmatter: ReviewerMetadata | None = None
    title: Annotated[str, TextTemplate("{value}")]
    next_steps: Annotated[list[str], AsNumberedList()]
    summary: Annotated[str, AsHeading()]
    findings: list[Finding]
