# ADR — Shape of Pydantic Models for Markdown Document Templates

- **Status:** Accepted
- **Date:** 2026-04-17
- **Decision makers:** Mark Norman; brainstorm session during CS7 Plan 4 design
- **Related plan:** `archipelago/docs/plans/2026-04-17-cs7-plan4-archipelago-agents-plan.md` (cross-repo — Archipelago is the first consumer)
- **Related prior work:** `src/agent_foundry/agents/schema_tools.py` (schema flattening for `--json-schema`); CS7 Plan 2's `AgentFilePath` in-loop verification mechanism (the declarative-validation pipeline documented here extends this)

## Status

Accepted. Agent Foundry will build its declarative markdown-document machinery around **Option (iii): annotation-driven domain models**. Options (i) and (ii), considered during the brainstorm, are rejected for the reasons documented below.

## Context

Archipelago's agents produce and consume markdown documents stored in a shared workspace volume. Earlier in the CS7 Plan 4 brainstorm, the team decided that the **template for each such document is a Pydantic model** — one canonical artifact from which Agent Foundry derives:

- a rendered markdown template the agent mimics (annotated skeleton)
- an instruction appendix (field-level semantics injected into the agent's instructions)
- a structural validator (parse markdown → instantiate model)
- an optional semantic validator (LLM-checked: does the content satisfy the field description?)
- a JSON schema (for `claude --json-schema` when the same content flows through the structured-output envelope)

A required property of Agent Foundry's declarative mechanism: the application (e.g., Archipelago) declares shapes and validation constraints; Agent Foundry performs the validation mechanically. **The application writes zero validation code.**

The validation pipeline is:

```
markdown → markdown-it-py AST → normalized JSON (flat list of element dicts) → Pydantic validation
```

Typed markdown elements (`MarkdownHeading`, `MarkdownSection`, `MarkdownCodeBlock`, `MarkdownTable`, ...) are modeled as a discriminated union with `kind` as the discriminator. The discriminator is required because (a) the chain passes through JSON and Pydantic needs a tag to recover the variant, (b) project convention forbids smart-union matching, and (c) `markdown-it-py` already emits a natural string tag per node.

The open question the ADR resolves: **given the Pydantic model is the canonical template, how should the application shape that model in relation to its domain types?**

Three concrete options were considered. All three were evaluated using the same worked example:

> A review with a title, description, and a list of findings. Each finding includes a code block and a section. Finding titles follow the pattern `"Finding N - <raw title>"`, e.g. `"Finding 3 - lack of coherence"`.

## Options Considered

### Option (i) — Pure structure; no separate domain model

The model is literally the document's shape. Every field's type is a markdown element or a composition thereof.

```python
class FindingBlock(BaseModel):
    heading: MarkdownHeading       # level 3, text "Finding N - <title>"
    code_block: MarkdownCodeBlock
    section: MarkdownSection

class ReviewDocument(BaseModel):
    title: MarkdownHeading         # level 1
    description: MarkdownSection
    findings_heading: MarkdownHeading  # level 2, text "Findings"
    findings: list[FindingBlock]

    @model_validator(mode="after")
    def _findings_titled_correctly(self) -> ReviewDocument:
        for i, fb in enumerate(self.findings, start=1):
            if not fb.heading.text.startswith(f"Finding {i} - "):
                raise ValueError(
                    f"findings[{i-1}].heading.text must start with 'Finding {i} - '"
                )
        return self
```

Downstream consumers retrieve the raw finding title via:

```python
raw_title = fb.heading.text.removeprefix(f"Finding {i} - ")
```

### Option (ii) — Two-tier: domain model + document model + projector

The application declares two parallel models — one domain, one document — plus a bidirectional projector function.

```python
# Domain model — what downstream code/agents consume
class Finding(BaseModel):
    title: str
    code: str
    code_language: str | None
    rationale_title: str
    rationale_body: str

class Review(BaseModel):
    title: str
    description: str
    findings: list[Finding]

# Document model — what the parsed markdown validates against
class FindingBlock(BaseModel):
    heading: MarkdownHeading
    code_block: MarkdownCodeBlock
    section: MarkdownSection

class ReviewDocument(BaseModel):
    title: MarkdownHeading
    description: MarkdownSection
    findings_heading: MarkdownHeading
    findings: list[FindingBlock]

# Projector — app-authored translation
def review_to_document(r: Review) -> ReviewDocument: ...
def document_to_review(d: ReviewDocument) -> Review:
    findings = []
    for i, fb in enumerate(d.findings, start=1):
        prefix = f"Finding {i} - "
        if not fb.heading.text.startswith(prefix):
            raise ValueError(...)
        findings.append(Finding(
            title=fb.heading.text.removeprefix(prefix),
            code=fb.code_block.content,
            code_language=fb.code_block.language,
            rationale_title=fb.section.title,
            rationale_body=fb.section.body,
        ))
    return Review(
        title=d.title.text,
        description=d.description.body,
        findings=findings,
    )
```

### Option (iii) — Domain fields with element-type annotations

A single domain model whose fields carry `Annotated[...]` metadata telling Agent Foundry's machinery how each field is rendered in markdown and located during parsing.

```python
class CodeSnippet(BaseModel):
    language: str | None
    content: str

class Finding(BaseModel):
    title: Annotated[
        str,
        AsHeading(level=3, text_template="Finding {ordinal} - {value}"),
    ]
    code: Annotated[CodeSnippet, AsCodeBlock()]
    rationale_title: Annotated[str, AsSectionTitle()]
    rationale_body: Annotated[str, AsSectionBody()]

class Review(BaseModel):
    title: Annotated[str, AsHeading(level=1)]
    description: Annotated[str, AsSection(title="Description")]
    findings: Annotated[
        list[Finding],
        AsList(heading="Findings", heading_level=2),
    ]
```

Downstream consumers retrieve the raw finding title via:

```python
raw_title = finding.title
```

`Annotated` attaches metadata to a type without changing the type. Type checkers see only the primary type (`str`, `list[Finding]`). Pydantic exposes the metadata at runtime via `model_fields[name].metadata`. Agent Foundry iterates fields, dispatches on annotation instance type, and applies per-annotation rendering / parsing / validation behavior.

## Analysis — by angle

The options were compared across five angles during the brainstorm. Each angle is reported here with its finding.

### Angle 1 — Declarative validation requirement (Agent Foundry owns validation; app writes zero code)

- **Option (i)** requires app-authored `@model_validator` methods for every cross-cutting rule (e.g., the `"Finding N - "` prefix check). **Violates the requirement.** Pushing the constraint into an annotation on the list field (`Annotated[list[...], HeadingOrdinalConstraint(...)]`) collapses the approach into (iii)'s machinery.
- **Option (ii)** puts structural validation in the document model and cross-cutting validation in the projector — which is app code. **Violates the requirement.**
- **Option (iii)** declares every rule as an annotation instance (`AsHeading(level=3, text_template=...)` *is* the structural + pattern rule). Agent Foundry reads the annotation and validates mechanically. **Satisfies the requirement natively.**

Winner: (iii). (i) and (ii) either fail the requirement or, when retrofitted to satisfy it, converge on (iii).

### Angle 2 — User experience of defining the domain model (app-author lens)

Holding validation requirements aside and assuming only heading-sequence validation is needed:

| Option | Effort | Domain clarity | Document-shape clarity |
|---|---|---|---|
| (i) | medium | **low** (domain and presentation mixed) | **high** (model reads top-to-bottom like the document) |
| (ii) | **high** (two models + projector, duplication to keep in sync) | **high** (clean domain surface) | medium (split across two types) |
| (iii) | **low** (one model, one annotation per field) | **high** (domain vocabulary leads) | medium (document shape reconstructed mentally from annotations) |

Summary: (i) shows the document best, (iii) shows the domain best, (ii) pays double to separate the two without a compensating benefit.

**Presentation vs. domain** — clarifying terms used above:
- **Domain** = the information content (a finding's title, its code, its rationale body).
- **Presentation** = how the information is rendered in markdown (heading level, bold title, code fence, section ordering, literal fixed strings like the word "Findings").

In (i), fields like `findings_heading: MarkdownHeading` with text `"Findings"` are pure presentation — no domain information. In (iii), presentation is a decoration on a domain field, not a field of its own.

### Angle 3 — Switching data channels: markdown ↔ JSON

Agents may communicate via markdown files in the workspace, JSON in the structured-output envelope, or a mix. The question: how easy is it to switch an agent (or a single message) from one channel to the other?

- **Option (i)**: "JSON" of the model is the **document AST** — `{"kind": "heading", "level": 3, "text": "Finding 1 - ..."}` — not natural domain JSON. A downstream agent receiving this as prompt input inherits presentation structure. To get clean domain JSON, you invent a parallel type and a projector — which is option (ii).
- **Option (ii)**: the domain model is channel-agnostic. JSON = Pydantic serialize. Markdown = project + render. Same domain type either way. Cost: two models + a projector per document type.
- **Option (iii)**: the domain model serializes natively to JSON (annotations are ignored by Pydantic's JSON serializer). For markdown, Agent Foundry's machinery uses the annotations to render/parse. **One model, two channels, no projector.**

### Angle 4 — Hybrid data sharing (slice of markdown document → JSON input to another agent)

Use case: Agent 1 produces a markdown file for "change set 2" containing all its steps. Agent 2 needs *only* "step 3" as JSON in its prompt.

- **Option (i)**: slicing `review.findings[2]` yields a `FindingBlock` of markdown elements. JSON-serializing it yields AST-flavored JSON, not natural domain JSON.
- **Option (ii)**: slice the domain model (`review.findings[2]: Finding`); serialize to JSON; drop into the prompt. Clean.
- **Option (iii)**: identical to (ii) with no projector overhead. **Clean.**

### Angle 5 — Ease of validating that a markdown file adheres to the template

- **Option (i)**: the validator must map the flat AST element list into the model's named fields via positional / structural matching ("first element is `MarkdownHeading` → `title`; second is `MarkdownSection` → `description`; next heading → `findings_heading`; then a repeating block shape → `findings`"). Requires a **centralized, generic AST matcher** with edge cases for reorder, missing blocks, and list absorption.
- **Option (ii)**: same AST-matcher problem, plus the projector may raise validation errors that are scattered in app code.
- **Option (iii)**: validator walks the model field-by-field. Each annotation is a self-contained rule: `AsHeading(level=3, text_template=...)` knows how to locate its element, check level, extract `{value}`, and report a localized error. **Validation is modular** — new constraints = new annotation types with their own handlers. No central AST matcher to extend.

Summary:

| | Structural validation | Adding new constraints |
|---|---|---|
| (i) | central AST matcher | extend matcher |
| (ii) | central AST matcher + projector | extend matcher + app code |
| (iii) | walk fields, dispatch to annotation handlers | add annotation type + handler |

## Decision

**Adopt Option (iii): annotation-driven domain models.** Agent Foundry ships a library of annotation classes (`AsHeading`, `AsSection`, `AsSectionTitle`, `AsSectionBody`, `AsCodeBlock`, `AsTable`, `AsList`, etc.), each with a rendering handler and a parsing/validation handler. Applications declare ordinary Pydantic domain models and annotate fields with the appropriate presentation rules. Agent Foundry owns the full pipeline: markdown → AST → normalized JSON → Pydantic validation; and Pydantic instance → markdown.

## Rationale

(iii) wins on every angle that was investigated:

- **Satisfies the declarative-validation requirement** (Angle 1) — app writes zero validation code.
- **Best domain clarity at the lowest authoring cost** (Angle 2) — one model, one annotation per field, domain vocabulary leads.
- **Channel-agnostic with no extra types** (Angles 3 and 4) — same model for markdown and JSON, no projector.
- **Modular validation that scales** (Angle 5) — each annotation is a local unit.

(i) fails on Angles 1, 3, 4 and is weak on 2. (ii) fails on Angle 1 and is costly on Angle 2. When either (i) or (ii) is retrofitted to meet the declarative-validation requirement, it converges on (iii)'s machinery. **The choice is forced once the requirements are made explicit.**

## Implications for Agent Foundry

Several non-trivial pieces of machinery are implied by this decision. They are listed here so the scope is visible when scheduling Plan 4 / Plan 5.

1. **Annotation library.** A set of annotation classes — `AsHeading`, `AsSection`, `AsSectionTitle`, `AsSectionBody`, `AsCodeBlock`, `AsTable`, `AsList`, etc. — each a plain Python object carrying its configuration (level, text template, title, language, etc.). This is the public vocabulary applications write against. New element types = new annotation classes.

2. **Typed markdown element models.** `MarkdownHeading`, `MarkdownSection`, `MarkdownCodeBlock`, `MarkdownTable`, etc., as a discriminated union keyed by `kind`. Used internally by the AST → normalized-JSON pipeline. Applications rarely reference these directly under (iii), but they are the runtime interchange form between the AST parser and the annotation handlers.

3. **AST parser integration.** A wrapper around `markdown-it-py` (or equivalent) that emits the normalized-JSON element list. Must be deterministic and well-tested against the markdown idioms agents will produce.

4. **Rendering engine.** Walks a Pydantic instance, dispatches on each field's annotation, emits markdown text. Responsible for heading levels, ordinal templates (e.g. `"Finding {ordinal} - {value}"`), code-fence language tags, list-section structure.

5. **Parsing / validation engine.** Walks a Pydantic model class, dispatches on each field's annotation, locates the corresponding element(s) in the AST, extracts field values, assigns to the model instance. Raises field-localized errors when an annotation's rule is violated.

6. **Annotated-skeleton template generator.** Renders a "blank document with field-description hints" that the agent receives as part of its instructions — the template it mimics. Derives heading text, level, and ordering from the annotation set.

7. **Instruction-appendix generator.** Emits a schema-aware appendix for the agent's instructions: per-field semantics, expected structure, constraints. Derived from annotations + field descriptions.

8. **Cross-channel consistency.** The same annotated domain model should drive both markdown round-trip and JSON-schema emission (`to_claude_code_schema`). Annotations that apply only to markdown (e.g., heading levels) must be ignored by the JSON-schema path.

9. **Error reporting contract.** When the agent's markdown fails validation, Agent Foundry must produce a field-localized, human-readable error that can be folded into the in-loop correction prompt (extending Plan 2's `AgentFilePath` correction mechanism). Errors must reference the model field and the annotation that failed, not just a low-level AST mismatch.

10. **Extensibility.** The annotation set is open: Archipelago (or another application) may define new annotation types and register their handlers with the platform. The platform provides a registration protocol; domain-specific annotations live in the application.

## Consequences

**Positive.**

- Declaring a new document template is a small, focused change: one Pydantic model, one annotation per field.
- Switching an agent from markdown to JSON (or vice versa) is a configuration-level change, not a type-system overhaul.
- Per-constraint reasoning: each annotation is a local, swappable unit. Validation complexity scales with the number of distinct rules, not the number of models.
- Domain models are honest — they describe the information, not its presentation. Agents and downstream code share the same vocabulary.
- The annotation set becomes a versionable, testable platform surface; regressions in one annotation type do not affect others.

**Negative / tradeoffs.**

- The document's overall shape is not visible at-a-glance in the model definition (option (i)'s strongest property). Authors reconstruct it mentally by walking the annotations or by reading the generated skeleton template. Mitigation: the annotated-skeleton generator (capability #6) is explicitly part of the machinery, so authors always have a rendered example to consult.
- The platform carries more code than a plain Pydantic setup would: seven-to-ten distinct engines/generators, each with its own tests. Mitigation: each engine is independent; most are straightforward to implement; they share a common representation (the element discriminated union).
- Cross-field coordination (e.g., a code block whose language comes from a sibling field) is awkward as a string reference (`language_from="code_language"`) and should be expressed as a nested typed pair (e.g., `Annotated[CodeSnippet, AsCodeBlock()]`). The convention has to be documented so applications don't reinvent the fragile string-reference form.
- Applications that want a *visible* document skeleton as code (option (i)'s benefit) do not get it. The rendered skeleton is a generated artifact, not a written one.

## Alternatives considered and rejected

- **Option (i): pure structure.** Rejected. Violates the declarative-validation requirement; produces AST-flavored JSON when channel-switched; mixes domain and presentation in the same model; requires a central AST matcher for validation.
- **Option (ii): two-tier with projector.** Rejected. Violates the declarative-validation requirement via app-authored projector code; doubles the type surface; requires maintaining two models in sync for every document type. The only angle on which (ii) matches (iii) is channel switching, and it pays for that parity with a projector that (iii) simply doesn't need.

## Open questions / future work

These do not block acceptance of this ADR, but they surface during implementation:

- **Parser strictness policy.** When the agent writes `## Reasoning` instead of `## Rationale`, does Agent Foundry strict-fail (and bounce the correction back to the agent via the in-loop mechanism), fuzzy-match, or match by ordinal position? The ADR favors strict-with-correction-loop because it produces the cleanest learning signal and the cleanest error message, but this is a policy knob that may need per-agent override.
- **Parsed-instance persistence.** Should the platform persist the parsed Pydantic instance as JSON alongside the markdown (`findings.md` + `findings.json`)? Cheap to do; removes re-parse friction for downstream consumers. Default: yes.
- **Override surface for annotations.** At v1, the annotation set is the full override surface (what level, what title, what template). Authors who want richer overrides (e.g., conditional rendering, computed heading text) will push for expansion. Policy: let the set grow from concrete need; do not speculate on additions.
- **Semantic validation (LLM-checked field conformance).** Optional layer on top of structural validation. Deferred until structural validation is in production; scope and cost to be revisited then.
- **Round-trip identity vs. semantic equivalence.** Agent Foundry targets **semantic equivalence** (parse-render-parse yields the same model instance), not byte-identical round-trip. Cosmetic formatting variation in the agent's output is tolerated as long as the instance is recoverable.
- **Relationship to `to_claude_code_schema`.** When the same annotated model is used for structured-output JSON via `--json-schema`, the schema flattener must ignore the markdown-specific annotations. To be implemented once the annotation library is concrete.

## Change log

- **2026-04-17** — ADR created. Decision accepted. Captures the brainstorm from CS7 Plan 4 design session.
