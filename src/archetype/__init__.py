"""Archetype — Pydantic as source of truth for agentic systems.

Core idea: declare a Pydantic data model once, and have one change to that
model propagate, without any other code edits, to every derived artifact
the model participates in — markdown templates, renderers, parsers,
validators, JSON schemas, instruction placeholders, and more.

Modules:

- ``archetype.markdown`` — typed markdown documents via Pydantic.
  Annotation-driven domain models, rendering, parsing, validation,
  subtree extraction, and heading-field introspection.

- ``archetype.templating`` — Jinja-based template resolution. Provides
  a preconfigured Jinja environment with markdown-aware globals
  (``template_fields``, ``render_template``) and a ``resolve()`` helper
  that renders a template string against a context object.

See individual submodule docstrings for details.
"""
