"""Normalize markdown-it-py AST tokens into a tree of typed BlockElement
instances + an optional MarkdownFrontmatter at the top.

Why a separate module: keeps the AST-token → typed-tree concern decoupled from
the projector (element-tree → domain instance). Tests can drive each layer
independently.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml
from markdown_it import MarkdownIt
from markdown_it.token import Token

from archetype.markdown.elements import (
    BlockElement,
    MarkdownBulletList,
    MarkdownCodeBlock,
    MarkdownFrontmatter,
    MarkdownHeading,
    MarkdownNumberedList,
    MarkdownParagraph,
    MarkdownTable,
    MarkdownTableRow,
)
from archetype.markdown.errors import MarkdownValidationError


@dataclass
class NormalizedDocument:
    """The output of `normalize()` — frontmatter (or None) plus the top-level
    block sequence. Each top-level heading carries its scoped body recursively."""

    frontmatter: MarkdownFrontmatter | None
    blocks: list[BlockElement]


def normalize(markdown: str) -> NormalizedDocument:
    """Parse markdown text and produce a normalized element tree."""

    fm, body = _split_frontmatter(markdown)
    # Use commonmark + the table plugin. NOT MarkdownIt("gfm-like"): that
    # preset enables the linkify rule, which requires the linkify-it-py
    # package (not in our deps) and crashes at parse time without it.
    md = MarkdownIt("commonmark").enable("table")
    tokens = md.parse(body)
    flat = _tokens_to_blocks(tokens)
    blocks_with_scope = _nest_headings_by_level(flat)
    return NormalizedDocument(frontmatter=fm, blocks=blocks_with_scope)


def _split_frontmatter(markdown: str) -> tuple[MarkdownFrontmatter | None, str]:
    if not markdown.startswith("---\n"):
        return None, markdown
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return None, markdown
    raw_yaml = markdown[4 : end + 1]
    rest = markdown[end + len("\n---\n") :]
    try:
        parsed = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError as exc:
        raise MarkdownValidationError(f"Frontmatter YAML is malformed: {exc}") from exc
    return MarkdownFrontmatter(raw_yaml=raw_yaml, parsed=parsed), rest


@dataclass
class _FlatBlock:
    """Pass-1 wrapper that carries the AST heading level alongside the typed
    element. Used only inside the normalizer; never escapes the module."""

    element: BlockElement
    level: int | None  # set only for MarkdownHeading


def _tokens_to_blocks(tokens: list[Token]) -> list[_FlatBlock]:
    """First pass: convert flat token stream into a flat list of `_FlatBlock`
    wrappers."""
    out: list[_FlatBlock] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.type == "heading_open":
            level = int(t.tag[1])  # 'h2' -> 2
            text = tokens[i + 1].content
            out.append(_FlatBlock(element=MarkdownHeading(text=text, body=[]), level=level))
            i += 3
        elif t.type == "paragraph_open":
            content = tokens[i + 1].content
            out.append(_FlatBlock(element=MarkdownParagraph(content=content), level=None))
            i += 3
        elif t.type == "fence":
            lang = t.info.strip() or None
            out.append(
                _FlatBlock(element=MarkdownCodeBlock(language=lang, content=t.content), level=None)
            )
            i += 1
        elif t.type == "bullet_list_open":
            items, advance = _collect_list_items(tokens, i, "bullet_list_close")
            out.append(_FlatBlock(element=MarkdownBulletList(items=items), level=None))
            i += advance
        elif t.type == "ordered_list_open":
            items, advance = _collect_list_items(tokens, i, "ordered_list_close")
            out.append(_FlatBlock(element=MarkdownNumberedList(items=items), level=None))
            i += advance
        elif t.type == "table_open":
            table, advance = _collect_table(tokens, i)
            out.append(_FlatBlock(element=table, level=None))
            i += advance
        else:
            i += 1
    return out


def _collect_list_items(tokens: list[Token], start: int, close_type: str) -> tuple[list[str], int]:
    items: list[str] = []
    i = start + 1
    while tokens[i].type != close_type:
        if tokens[i].type == "list_item_open":
            items.append(tokens[i + 2].content)
        i += 1
    return items, (i - start) + 1


def _collect_table(tokens: list[Token], start: int) -> tuple[MarkdownTable, int]:
    columns: list[str] = []
    rows: list[MarkdownTableRow] = []
    i = start + 1
    in_header = False
    in_body = False
    cur_row: list[str] = []
    while tokens[i].type != "table_close":
        t = tokens[i]
        if t.type == "thead_open":
            in_header = True
        elif t.type == "thead_close":
            in_header = False
        elif t.type == "tbody_open":
            in_body = True
        elif t.type == "tbody_close":
            in_body = False
        elif t.type == "tr_open":
            cur_row = []
        elif t.type == "tr_close":
            if in_header:
                columns = cur_row
            elif in_body:
                rows.append(MarkdownTableRow(cells=cur_row))
        elif t.type in ("th_open", "td_open"):
            cur_row.append(tokens[i + 1].content)
        i += 1
    return MarkdownTable(columns=columns, rows=rows), (i - start) + 1


def _nest_headings_by_level(flat: list[_FlatBlock]) -> list[BlockElement]:
    """Second pass: turn flat block list into a tree by nesting blocks under
    the most recent open heading scope."""
    root: list[BlockElement] = []
    stack: list[tuple[int, MarkdownHeading]] = []
    for fb in flat:
        block = fb.element
        if isinstance(block, MarkdownHeading):
            assert fb.level is not None
            level = fb.level
            while stack and stack[-1][0] >= level:
                stack.pop()
            target = stack[-1][1].body if stack else root
            target.append(block)
            stack.append((level, block))
        else:
            target = stack[-1][1].body if stack else root
            target.append(block)
    return root
