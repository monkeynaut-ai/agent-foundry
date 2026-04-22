"""Deterministic markdown renderer for MarkdownHeader/MarkdownDocument templates and instances.

Two entry points:
  - render_template(model_class) -> str:  the annotated skeleton
  - render_instance(instance)    -> str:  a populated document

Both walk fields in declaration order, dispatch on field role (structural vs
annotation-driven), and emit the corresponding markdown. Heading levels are
inferred from rendering context (top-level model is level 1; nested headers
recurse with level + 1). A render-time guard raises if any heading would
emit at level > 6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from archetype.markdown._shared import get_role_annotation, resolve_wrapper_text, snake_to_title
from archetype.markdown.errors import MarkdownTemplateError

if TYPE_CHECKING:
    from archetype.markdown.template_model import MarkdownHeader


_MAX_HEADING_LEVEL = 6


def render_template(model_class: type[MarkdownHeader], *, current_level: int = 1) -> str:
    """Render the annotated skeleton template for a MarkdownHeader subclass."""
    _guard_heading_level(model_class, current_level)
    title_text = _derive_title_text_for_template(model_class)
    parts: list[str] = [f"{'#' * current_level} {title_text}", ""]

    body_level = current_level + 1
    for name, field in model_class.model_fields.items():
        if name in ("title", "frontmatter"):
            continue
        rendered = _render_body_field_template(name, field, body_level, model_class)
        if rendered:
            parts.append(rendered)
            parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def _derive_title_text_for_template(model_class: type[MarkdownHeader]) -> str:
    """Skeleton title text. If title field has TextTemplate, use the literal template
    so the placeholder is visible in the skeleton."""
    title_field = model_class.model_fields.get("title")
    if title_field:
        from archetype.markdown.annotations import TextTemplate

        for m in title_field.metadata or []:
            if isinstance(m, TextTemplate):
                return m.template
    return f"<!-- {model_class.__name__} title -->"


def _render_body_field_template(name: str, field: object, level: int, owning_class: type) -> str:
    from typing import get_args, get_origin

    from archetype.markdown.annotations import (
        AsBulletList,
        AsCodeBlock,
        AsHeading,
        AsNumberedList,
        AsTable,
    )
    from archetype.markdown.template_model import MarkdownHeader

    ann = get_role_annotation(field)
    field_type = field.annotation  # type: ignore[attr-defined]

    if isinstance(ann, AsHeading):
        _guard_heading_level(owning_class, level)
        heading_text = snake_to_title(name)
        description_comment = _description_comment(field)
        return f"{'#' * level} {heading_text}\n\n{description_comment}"
    if isinstance(ann, AsCodeBlock):
        lang = ann.language or ""
        return f"```{lang}\n<!-- {name} code -->\n```"
    if isinstance(ann, AsBulletList):
        return f"- <!-- {name} item 1 -->\n- <!-- {name} item 2 -->"
    if isinstance(ann, AsNumberedList):
        return f"1. <!-- {name} item 1 -->\n2. <!-- {name} item 2 -->"
    if isinstance(ann, AsTable):
        return _render_table_template(name, field)
    # Single MarkdownHeader-typed field: recurse at this level.
    if isinstance(field_type, type) and issubclass(field_type, MarkdownHeader):
        return render_template(field_type, current_level=level)
    # list[MarkdownHeader-subclass]: wrapper heading + item template.
    if get_origin(field_type) is list:
        args = get_args(field_type)
        if args and isinstance(args[0], type) and issubclass(args[0], MarkdownHeader):
            wrapper_text = resolve_wrapper_text(name, field)
            _guard_heading_level(owning_class, level)
            wrapper = f"{'#' * level} {wrapper_text}"
            item_template = render_template(args[0], current_level=level + 1)
            return f"{wrapper}\n\n{item_template}"
    return ""  # unrecognised field shape; no output


def _render_table_template(name: str, field: object) -> str:
    from typing import get_args, get_origin

    from pydantic import BaseModel

    field_type = field.annotation  # type: ignore[attr-defined]
    if get_origin(field_type) is not list:
        return ""
    inner = get_args(field_type)[0]
    if not (isinstance(inner, type) and issubclass(inner, BaseModel)):
        return ""
    column_names = [snake_to_title(fname) for fname in inner.model_fields]
    header = "| " + " | ".join(column_names) + " |"
    sep = "|" + "|".join(["---"] * len(column_names)) + "|"
    placeholder = "| " + " | ".join([f"<!-- {fn} -->" for fn in inner.model_fields]) + " |"
    return f"{header}\n{sep}\n{placeholder}"


def _description_comment(field: object) -> str:
    desc = getattr(field, "description", None)
    if desc:
        return f"<!-- {desc} -->"
    return "<!-- field body -->"


def _rebase_headings_in_body(text: str, *, target_level: int) -> str:
    """Rebase heading markers in a body string so the shallowest heading ends
    up at `target_level` in the rendered document.

    The stored value uses `##` for its top-level sub-headings (level 2). When
    the `AsHeading` field is rendered at document level `L`, its content should
    start at level `L+1`. This function shifts all heading markers by
    `(target_level - 2)` levels so that `##` → `#{target_level}`.

    If `target_level <= 2` (field rendered at level 1), no shift is needed and
    the text is returned unchanged. Lines that are not heading markers are
    passed through verbatim."""
    import re

    delta = target_level - 2
    if delta <= 0:
        return text

    def _shift(m: re.Match[str]) -> str:
        hashes = m.group(1)
        new_level = len(hashes) + delta
        return "#" * new_level + m.group(2)

    return re.sub(r"^(#{1,6})([ \t])", _shift, text, flags=re.MULTILINE)


def _guard_heading_level(model_class: type, level: int) -> None:
    if level > _MAX_HEADING_LEVEL:
        raise MarkdownTemplateError(
            f"Cannot render {model_class.__name__} at heading level {level}; "
            f"markdown supports a maximum of level {_MAX_HEADING_LEVEL}. "
            f"Reduce nesting in the template."
        )


def render_instance(
    instance: MarkdownHeader,
    *,
    current_level: int = 1,
    ordinal: int | None = None,
) -> str:
    """Render a populated MarkdownHeader instance to markdown text.

    `ordinal` is the 1-based position when rendered as a list item of a parent
    list field. Standalone calls leave it None; TextTemplate's `{ordinal}`
    defaults to '1' (see _resolve_title_text)."""
    from archetype.markdown.template_model import MarkdownDocument

    parts: list[str] = []

    # 1. Frontmatter (only on MarkdownDocument with frontmatter set)
    if isinstance(instance, MarkdownDocument) and instance.frontmatter is not None:
        parts.append(_render_frontmatter_instance(instance.frontmatter))

    # 2. Title at current_level
    _guard_heading_level(type(instance), current_level)
    title_text = _resolve_title_text(instance, ordinal=ordinal)
    parts.append(f"{'#' * current_level} {title_text}")

    # 3. Body fields in declaration order at current_level + 1
    body_level = current_level + 1
    for name, field in type(instance).model_fields.items():
        if name in ("title", "frontmatter"):
            continue
        value = getattr(instance, name)
        rendered = _render_body_field_instance(name, field, value, body_level, type(instance))
        if rendered:
            parts.append(rendered)

    return "\n\n".join(p for p in parts if p).rstrip() + "\n"


def _resolve_title_text(instance: MarkdownHeader, *, ordinal: int | None) -> str:
    from archetype.markdown.annotations import TextTemplate

    title_field = type(instance).model_fields.get("title")
    if title_field:
        for m in title_field.metadata or []:
            if isinstance(m, TextTemplate):
                template = m.template
                if "{ordinal}" in template:
                    template = template.replace(
                        "{ordinal}", str(ordinal if ordinal is not None else 1)
                    )
                if "{value}" in template:
                    template = template.replace("{value}", instance.title)
                return template
    return instance.title


def _render_frontmatter_instance(frontmatter: BaseModel) -> str:
    import yaml

    data = frontmatter.model_dump()
    yaml_text = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    return f"---\n{yaml_text}---"


def _render_body_field_instance(
    name: str, field: object, value: object, level: int, owning_class: type
) -> str:
    from typing import cast, get_args, get_origin

    from archetype.markdown.annotations import (
        AsBulletList,
        AsCodeBlock,
        AsHeading,
        AsNumberedList,
        AsTable,
    )
    from archetype.markdown.template_model import MarkdownHeader

    ann = get_role_annotation(field)
    field_type = field.annotation  # type: ignore[attr-defined]

    if isinstance(ann, AsHeading):
        _guard_heading_level(owning_class, level)
        heading_text = snake_to_title(name)
        body_text = str(value) if value is not None else ""
        # Rebase heading markers in body text so that `## Sub` (level 2 in the
        # stored value) becomes `#{level+1} Sub` in the document, ensuring the
        # normalizer nests it inside this heading rather than treating it as a
        # sibling. `_serialize_block_body` undoes this by emitting `##` for
        # first-level sub-headings when reconstructing the field value.
        body_text = _rebase_headings_in_body(body_text, target_level=level + 1)
        return f"{'#' * level} {heading_text}\n\n{body_text}"
    if isinstance(ann, AsCodeBlock):
        lang = ann.language or ""
        return f"```{lang}\n{value}\n```"
    if isinstance(ann, AsBulletList):
        items = "\n".join(f"- {item}" for item in cast(list[str], value or []))
        return items
    if isinstance(ann, AsNumberedList):
        items = "\n".join(f"{i + 1}. {item}" for i, item in enumerate(cast(list[str], value or [])))
        return items
    if isinstance(ann, AsTable):
        return _render_table_instance(field_type, cast(list[object], value or []))
    if isinstance(field_type, type) and issubclass(field_type, MarkdownHeader):
        return render_instance(cast(MarkdownHeader, value), current_level=level)
    if get_origin(field_type) is list:
        args = get_args(field_type)
        if args and isinstance(args[0], type) and issubclass(args[0], MarkdownHeader):
            wrapper_text = resolve_wrapper_text(name, field)
            _guard_heading_level(owning_class, level)
            wrapper = f"{'#' * level} {wrapper_text}"
            items_list = cast(list[MarkdownHeader], value or [])
            if not items_list:
                return wrapper
            item_parts = []
            for idx, item in enumerate(items_list, start=1):
                rendered = render_instance(item, current_level=level + 1, ordinal=idx)
                item_parts.append(rendered)
            return wrapper + "\n\n" + "\n\n".join(item_parts)
    return ""


def _render_table_instance(field_type: object, value: list[object]) -> str:
    from typing import get_args

    inner = get_args(field_type)[0]
    column_names = [snake_to_title(fname) for fname in inner.model_fields]
    header = "| " + " | ".join(column_names) + " |"
    sep = "|" + "|".join(["---"] * len(column_names)) + "|"
    rows = []
    for item in value:
        cells = [str(getattr(item, fname)) for fname in inner.model_fields]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, sep, *rows])
