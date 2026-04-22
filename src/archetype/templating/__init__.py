"""Jinja-based template resolution with markdown-aware globals.

``archetype.templating`` composes Jinja2 with the markdown package's
introspection and rendering primitives. Products call ``resolve()`` from
wherever they need one-pass templating against per-run context —
most commonly an agent's ``instructions_provider(state)`` or a
prompt-building callable.

Two Jinja globals are registered in the environment and always available
inside templates:

  - ``template_fields(ModelClass)`` — iterate heading-field metadata for a
    ``MarkdownHeader`` (or ``MarkdownDocument``) subclass; yields
    ``FieldInfo`` entries with ``.heading`` and ``.description``.

  - ``render_template(ModelClass)`` — emit the full annotated markdown
    skeleton for a template model.

Example::

    from archetype.templating import resolve

    def designer_instructions_provider(state: DesignerInput) -> str:
        return resolve(
            _load_template(),
            feature=state.feature_definition,
        )

    # Inside the template:
    #
    #   The feature definition has these sections:
    #   {% for field in template_fields(FeatureDefinition) %}
    #   - **{{ field.heading }}** — {{ field.description }}
    #   {% endfor %}
    #
    #   Your output must match this structure:
    #
    #   {{ render_template(DesignDocument) }}

Convention (documented; not runtime-enforced): templates use only
``{{ path }}``, ``{% for x in path %}...{% endfor %}``, and the two
registered globals. No filters, conditionals, macros, includes, or
inheritance. If a real need arises, lift the restriction deliberately.
"""

from archetype.templating.environment import build_environment
from archetype.templating.resolve import resolve

__all__ = [
    "build_environment",
    "resolve",
]
