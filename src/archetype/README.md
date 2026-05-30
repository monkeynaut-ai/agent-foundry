# Archetype

Pydantic as the single source of truth for agentic systems.

## 1. Purpose

Agentic systems constantly move structured data across a fuzzy typed/textual (deterministic/generative)
boundary: a prompt describes the expected output shape, the LLM emits
markdown, code parses that markdown back into typed objects, and a downstream
agent re-renders it for the next step. When the prompt, the parser, and the
type definition live in separate places, they drift — silently — and that
drift is the most common source of bugs in LLM pipelines.

Archetype eliminates the drift by making one annotated Pydantic class the
authoritative declaration. From that single class, the library derives:

- the **markdown template** the agent is instructed to fill in,
- the **renderer** that turns instances back into markdown,
- the **parser/validator** that turns LLM output back into instances,
- the **JSON schema** for tool/structured-output integration,
- the **field introspection** that prompts use to describe their own
  expected sections (`template_fields(Model)`),
- the **Jinja resolution context** for one-pass instruction templates.

A schema change in one place propagates everywhere automatically. Renaming
a field, adding a section, or changing a heading's structure cannot
desynchronize the prompt from the parser, because both are projections of
the same class.

## 2. Usage

Archetype has two submodules:

- `archetype.markdown` — typed markdown documents driven by annotated
  Pydantic models (template generation, rendering, parsing, validation,
  subtree extraction, heading-field introspection).
- `archetype.templating` — a preconfigured Jinja environment with
  markdown-aware globals (`template_fields`, `render_template`) and a
  `resolve()` helper for one-pass instruction templating.

### Declaring a document

```python
from typing import Annotated
from archetype.markdown import (
    MarkdownDocument, MarkdownHeader,
    AsHeading, AsBulletList, TextTemplate,
)

class Finding(MarkdownHeader):
    title: Annotated[str, TextTemplate("Finding {ordinal} - {value}")]
    description: Annotated[str, AsHeading()]
    evidence: Annotated[list[str], AsBulletList()]

class Review(MarkdownDocument):
    title: Annotated[str, TextTemplate("{value}")]
    summary: Annotated[str, AsHeading()]
    findings: list[Finding]
```

### Rendering, parsing, introspecting

```python
from archetype.markdown import (
    render_template, render_instance, validate_markdown, template_fields,
)

# Skeleton markdown to embed in an agent's prompt
template_md = render_template(Review)

# Turn an LLM's markdown reply back into a typed instance
review: Review = validate_markdown(llm_output, Review)

# Re-render an instance to markdown (e.g. as input to a downstream agent)
markdown = render_instance(review)

# Iterate heading metadata for prompt construction
for field in template_fields(Review):
    print(field.heading, field.description)
```

### Instruction templates with Jinja

```python
from archetype.templating import resolve

def designer_instructions_provider(state: DesignerInput) -> str:
    return resolve(
        _load_template(),
        feature=state.feature_definition,
    )
```

Inside the template:

```jinja
The feature definition has these sections:
{% for field in template_fields(FeatureDefinition) %}
- **{{ field.heading }}** — {{ field.description }}
{% endfor %}

Your output must match this structure:

{{ render_template(DesignDocument) }}
```

Templates use only `{{ path }}`, `{% for x in path %}…{% endfor %}`, and the
two registered globals — no filters, conditionals, macros, includes, or
inheritance. The restriction is convention, not runtime-enforced.

## 3. What the Pydantic model drives

The annotated model is the hub; every artifact downstream is a derivation
of it. There is no parallel source of truth for any of these arrows.

```
                            ┌──────────────────────────┐
                            │   Annotated Pydantic     │
                            │   model (your class)     │
                            │                          │
                            │  • field names + types   │
                            │  • Annotated[…] markers: │
                            │      AsHeading           │
                            │      AsCodeBlock         │
                            │      AsTable             │
                            │      AsBulletList        │
                            │      AsNumberedList      │
                            │      TextTemplate        │
                            │  • nested MarkdownHeader │
                            │    subclasses            │
                            └─────────────┬────────────┘
                                          │
       ┌──────────────────┬───────────────┼───────────────┬──────────────────┐
       │                  │               │               │                  │
       ▼ drives           ▼ drives        ▼ controls      ▼ validates        ▼ exposes
┌─────────────┐  ┌─────────────────┐ ┌──────────────┐ ┌─────────────┐ ┌────────────────┐
│ render_     │  │ render_instance │ │ validate_    │ │ Pydantic    │ │ template_      │
│ template()  │  │ ()              │ │ markdown()   │ │ field +     │ │ fields() →     │
│             │  │                 │ │              │ │ structural  │ │ FieldInfo for  │
│ skeleton    │  │ instance →      │ │ markdown →   │ │ meta-       │ │ each heading   │
│ markdown    │  │ markdown        │ │ instance     │ │ validation  │ │ (.heading,     │
│ for prompts │  │                 │ │              │ │ at class    │ │  .description) │
│             │  │                 │ │              │ │ definition  │ │                │
└─────────────┘  └─────────────────┘ └──────────────┘ └─────────────┘ └────────────────┘
       │                  │                 │                                │
       │                  │                 │                                │
       └──────────┬───────┴─────────────────┴────────────────────────────────┘
                  │
                  ▼ all reachable inside Jinja via
        ┌──────────────────────────────────────┐
        │  archetype.templating.resolve(...)   │
        │                                      │
        │  globals: template_fields,           │
        │           render_template            │
        │                                      │
        │  one-pass agent-instruction rendering│
        └──────────────────────────────────────┘
                  │
                  ▼ also drives
        ┌──────────────────────────────────────┐
        │  Model.model_json_schema() — JSON    │
        │  schema for structured-output / tool │
        │  integrations (free from Pydantic)   │
        └──────────────────────────────────────┘
                  │
                  ▼ supports
        ┌──────────────────────────────────────┐
        │  extract_subtree() — slice a typed   │
        │  subtree out of a larger document    │
        └──────────────────────────────────────┘
```

### Per-arrow summary

| Arrow                  | Reads from the model                                  | Produces                                |
| ---------------------- | ----------------------------------------------------- | --------------------------------------- |
| `render_template`      | field names, annotations, nested types                | skeleton markdown for prompts           |
| `render_instance`      | instance values + annotations                         | markdown serialization                  |
| `validate_markdown`    | field types, annotations, structural rules            | typed instance (or `MarkdownValidationError`) |
| Meta-validation hook   | class structure at definition time                    | early `MarkdownError` on malformed templates |
| `template_fields`      | heading-introducing fields and their docstrings       | `FieldInfo(heading, description)` stream |
| `extract_subtree`      | nested `MarkdownHeader` types                         | typed slice of a larger document        |
| `Model.model_json_schema()` | field types (Pydantic-native)                    | JSON Schema for structured-output APIs  |
| `resolve()` (Jinja)    | the model, via `template_fields` / `render_template`  | fully-resolved instruction string       |

The takeaway: edit the annotated Pydantic class, and every artifact above
follows. No other file needs to change for the prompt, the parser, the
schema, and the renderer to stay in agreement.
