"""AST-level subtree extractor.

Locates a heading by level + exact text match, returns the heading's full scope
as a markdown string with heading levels rebased so the matched heading becomes
level 1. The result can be passed directly to validate_markdown against a
template model whose top heading is at level 1.
"""

from __future__ import annotations

from markdown_it import MarkdownIt
from markdown_it.token import Token

from archetype.markdown.errors import MarkdownExtractionError


def extract_subtree(
    markdown: str,
    *,
    heading_level: int,
    title_match: str,
) -> str:
    """Return the subtree under the heading at `heading_level` whose text
    equals `title_match`. Heading levels in the result are rebased so the
    matched heading is level 1."""

    md = MarkdownIt("commonmark").enable("table")
    tokens = md.parse(markdown)

    match_idx = _find_matching_heading(tokens, heading_level, title_match)
    if match_idx is None:
        raise MarkdownExtractionError(
            f"Heading at level {heading_level} with text {title_match!r} not found in markdown."
        )

    end_idx = _find_scope_end(tokens, match_idx, heading_level)

    delta = heading_level - 1
    sub_tokens = _rebase_heading_levels(tokens[match_idx:end_idx], delta)

    return _render_tokens_to_markdown(sub_tokens)


def _find_matching_heading(tokens: list[Token], level: int, text: str) -> int | None:
    matches: list[int] = []
    for i, t in enumerate(tokens):
        if (
            t.type == "heading_open"
            and int(t.tag[1]) == level
            and i + 1 < len(tokens)
            and tokens[i + 1].content == text
        ):
            matches.append(i)
    if len(matches) > 1:
        raise MarkdownExtractionError(
            f"Found multiple ({len(matches)}) headings at level {level} with text "
            f"{text!r}; extract_subtree requires a unique match in Phase 1."
        )
    return matches[0] if matches else None


def _find_scope_end(tokens: list[Token], start: int, scope_level: int) -> int:
    i = start + 3
    while i < len(tokens):
        t = tokens[i]
        if t.type == "heading_open" and int(t.tag[1]) <= scope_level:
            return i
        i += 1
    return len(tokens)


def _rebase_heading_levels(tokens: list[Token], delta: int) -> list[Token]:
    out = []
    for t in tokens:
        if t.type in ("heading_open", "heading_close"):
            new_level = int(t.tag[1]) - delta
            new_t = Token(t.type, f"h{new_level}", t.nesting)
            new_t.markup = "#" * new_level
            new_t.content = t.content
            out.append(new_t)
        else:
            out.append(t)
    return out


def _render_tokens_to_markdown(tokens: list[Token]) -> str:
    """Re-serialize a token stream back to markdown text. Minimal renderer
    handling headings, paragraphs, lists, and code blocks for round-trip via
    validate_markdown."""

    parts: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.type == "heading_open":
            level = int(t.tag[1])
            text = tokens[i + 1].content
            parts.append(f"{'#' * level} {text}")
            i += 3
        elif t.type == "paragraph_open":
            text = tokens[i + 1].content
            parts.append(text)
            i += 3
        elif t.type == "fence":
            lang = t.info or ""
            parts.append(f"```{lang}\n{t.content}```")
            i += 1
        elif t.type == "bullet_list_open":
            i += 1
            items = []
            while tokens[i].type != "bullet_list_close":
                if tokens[i].type == "list_item_open":
                    items.append(tokens[i + 2].content)
                i += 1
            parts.append("\n".join(f"- {it}" for it in items))
            i += 1
        elif t.type == "ordered_list_open":
            i += 1
            items = []
            while tokens[i].type != "ordered_list_close":
                if tokens[i].type == "list_item_open":
                    items.append(tokens[i + 2].content)
                i += 1
            parts.append("\n".join(f"{n + 1}. {it}" for n, it in enumerate(items)))
            i += 1
        elif t.type == "table_open":
            i += 1
            header_cells: list[str] = []
            data_rows: list[list[str]] = []
            cur_row: list[str] = []
            in_header = False
            while tokens[i].type != "table_close":
                tt = tokens[i]
                if tt.type == "thead_open":
                    in_header = True
                elif tt.type == "thead_close":
                    in_header = False
                elif tt.type == "tr_open":
                    cur_row = []
                elif tt.type == "tr_close":
                    if in_header:
                        header_cells = cur_row
                    else:
                        data_rows.append(cur_row)
                elif tt.type in ("th_open", "td_open"):
                    cur_row.append(tokens[i + 1].content)
                i += 1
            sep = "|" + "|".join(["---"] * len(header_cells)) + "|"
            parts.append("| " + " | ".join(header_cells) + " |")
            parts.append(sep)
            for row in data_rows:
                parts.append("| " + " | ".join(row) + " |")
            i += 1  # skip table_close
        else:
            i += 1
    return "\n\n".join(parts) + "\n"
