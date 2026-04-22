"""``resolve()`` — render a Jinja-templated text document against a context.

Composes the markdown-aware Jinja environment with the caller's context
and returns the resolved string. Agent-side products call this wherever
they need one-pass template resolution — agent instructions, prompts, PR
descriptions, and similar markdown artifacts.

Example::

    from archetype.templating import resolve

    def designer_instructions_provider(state: DesignerInput) -> str:
        return resolve(
            _load_template(),
            feature=state.feature_definition,
        )

Undefined paths raise ``jinja2.UndefinedError`` (``StrictUndefined`` semantics),
so template bugs surface immediately rather than as silent empty output.
"""

from __future__ import annotations

from typing import Any

import jinja2

from archetype.templating.environment import build_environment


def resolve(template_text: str, **context: Any) -> str:
    """Resolve a Jinja template against the given context and return the
    rendered string.

    - ``template_text``: the raw Jinja template (usually loaded from a
      markdown file bundled with the product's code).
    - ``**context``: keyword arguments bound as variables inside the template.

    Raises ``jinja2.UndefinedError`` on any undefined variable or attribute
    access (``StrictUndefined`` semantics).
    """

    env = build_environment()
    env.undefined = jinja2.StrictUndefined
    return env.from_string(template_text).render(**context)
