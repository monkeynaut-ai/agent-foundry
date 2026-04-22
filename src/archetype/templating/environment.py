"""Jinja2 environment factory with markdown-aware globals.

Builds an ``Environment`` preconfigured for text/markdown output (no
autoescape, whitespace trimmed around block tags) and registers two
globals that templates rely on:

  - ``template_fields(ModelClass)`` — returns a list of ``FieldInfo``
    describing the model's body heading sections. See
    ``archetype.markdown.introspection``.

  - ``render_template(ModelClass)`` — returns the full annotated markdown
    skeleton for the model. See ``archetype.markdown.renderer``.

Convention (documented; not runtime-enforced): templates use only
``{{ path }}``, ``{% for x in path %}...{% endfor %}``, and the two globals
above. No filters, conditionals, macros, includes, or inheritance. If a
real need arises, lift the restriction deliberately.
"""

from __future__ import annotations

import jinja2

from archetype.markdown.introspection import template_fields
from archetype.markdown.renderer import render_template


def build_environment() -> jinja2.Environment:
    """Return a Jinja2 ``Environment`` ready to render markdown templates.

    Configuration:
      - ``trim_blocks=True``: strip trailing newline after block tags.
      - ``lstrip_blocks=True``: strip leading whitespace before block tags.
      - ``keep_trailing_newline=True``: preserve a file's trailing newline.
      - ``autoescape=False``: markdown output needs literal characters.

    Registered globals:
      - ``template_fields``: the heading-field accessor.
      - ``render_template``: the markdown skeleton renderer.
    """

    env = jinja2.Environment(
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,
    )
    env.globals["template_fields"] = template_fields
    env.globals["render_template"] = render_template
    return env
