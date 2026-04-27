# Open-Sourcing the `agent_foundry.markdown` Package

A plan for extracting `src/agent_foundry/markdown/` into a standalone, public
open-source project.

## Summary

The `agent_foundry.markdown` package is a declarative markdown-template
library: users subclass `MarkdownDocument` / `MarkdownHeader` with typed
Pydantic fields, annotate each field with a role (`AsHeading`, `AsTable`,
`AsBulletList`, `AsCodeBlock`, `AsNumberedList`, `TextTemplate`), and get
deterministic round-tripping between instances and markdown documents for
free — plus a structural meta-validator that fires at class-definition
time.

Of every module in the repo, this one is by far the strongest candidate for
extraction. It is already library-shaped: zero cross-package coupling, a small
coherent public API, its own error hierarchy, thorough tests, and a clean
commit history showing it was built as a library from day one. External
dependencies are limited to `pydantic`, `markdown-it-py`, and `PyYAML` — all
permissively licensed and already in this project's lock file.

The only caveat is maturity: Phase 1 was committed on the day this document
was written (2026-04-19). Apart from its own test suite, nothing inside
`agent_foundry` currently imports the package — Archipelago is the intended
first consumer but has not yet adopted it. Extraction therefore carries no
entanglement cost, but also ships with no production-usage evidence.

---

## Why This Package Is A Strong Candidate

### Self-containment

Every internal import in the package stays under `agent_foundry.markdown.*`.
There are no references to `agent_foundry.primitives`, `agent_foundry.compiler`,
`agent_foundry.orchestration`, `agent_foundry.agents`, `agent_foundry.models`,
or any other sibling package. The package is internally cohesive and externally
isolated — a textbook "cut line."

### Minimal, permissively-licensed dependencies

Only three third-party libraries are imported anywhere in the package:

| Dependency       | Role                                        | License    |
|------------------|---------------------------------------------|------------|
| `pydantic`       | Base class for templates; field metadata    | MIT        |
| `markdown-it-py` | CommonMark + GFM parser                     | MIT        |
| `PyYAML`         | Frontmatter serialization                   | MIT        |

No vendor SDKs, no LLM clients, no containerization libs — none of the
project-specific surface that couples the rest of Agent Foundry to Docker,
Claude Code, or LangGraph.

### Small, coherent public API

The package exports seventeen symbols from `agent_foundry/markdown/__init__.py`:

- **Base classes**: `MarkdownDocument`, `MarkdownHeader`
- **Annotations**: `AsHeading`, `AsCodeBlock`, `AsTable`, `AsBulletList`,
  `AsNumberedList`, `TextTemplate`
- **Operations**: `render_template`, `render_instance`, `validate_markdown`,
  `extract_subtree`
- **Errors**: `MarkdownError`, `MarkdownTemplateError`,
  `MarkdownValidationError`, `MarkdownExtractionError`

All private machinery (`_ast_normalizer`, `_projector`, `_shared`,
`meta_validation`) is prefixed with `_` or intentionally unexported.

### No domain leakage

Searching the package for product-specific terms (`archipelago`, `foundry`,
`agent-foundry`, hard-coded paths, URLs, secrets, customer names) surfaces
only import paths and a single docstring pointer to the governing ADR. The
code itself is product-neutral.

### Comprehensive tests

Twelve test files covering ~1,262 lines for ~1,570 lines of source — a very
healthy ratio. A dedicated `test_public_api.py` pins the export surface; a
`test_round_trip.py` exercises render → parse idempotency; each subsystem
(annotations, AST normalizer, projector, renderer, meta-validation,
extractor) has focused unit tests plus a fixtures module with realistic
sample models.

### Own error hierarchy

`MarkdownError` as the common base, with three purpose-specific subclasses.
`MarkdownTemplateError` also inherits from `TypeError` so it can fire from
`__pydantic_init_subclass__` without breaking Python's "subclass construction
raised" convention.

### Commit history reveals intentional library design

The git log for `src/agent_foundry/markdown/` reads like a library author's
worklog: twenty-five focused commits, each introducing one element type, one
annotation, one meta-validation rule, or one renderer phase. Feature commits
dominate; bugfix commits cite round-trip discrepancies. This is not code that
accreted over time around changing product demands — it was designed up
front as a reusable mechanism.

### Fills an unserved gap in an established-but-narrow ecosystem

This is not a mass-market problem. The dominant solution for "structured
LLM output with Pydantic" is JSON, and the market for JSON-based structured
output (`instructor`, `outlines`, BAML, native provider modes) dwarfs the
market for markdown-structured output by roughly three orders of magnitude.

What this package solves is narrower and currently unserved: **typed
Pydantic ↔ markdown document round-trip**. Adjacent one-way tools exist
and have measurable adoption — `markdown-mdantic` (~5.3K downloads/month)
and `docdantic` (~760/month) both generate markdown from Pydantic models
but do not parse markdown back. The closest round-trip cousin,
`python-frontmatter` (~6.8M/month), solves a thin slice (YAML frontmatter
only). The full-document round-trip case is not covered by anything we
found.

The audience, extrapolated from those adoption numbers and the demand
signals catalogued in the next section, is likely **low thousands of
builders** rather than tens of thousands — but it is measurable, has
independent practitioners describing the exact pattern in the wild, and
has no existing library that binds a Pydantic type to a full markdown
document shape with render / parse / validate as three free operations
on that binding.

See the next section, "Where the Need Is Being Expressed," for the
evidence behind these numbers.

---

## Where the Need Is Being Expressed

This section catalogues the concrete places the need for typed,
schema-bound markdown surfaces in public channels. The goal is not to
argue "big market"; it is to document **where** the pain is visible, so
a future maintainer can calibrate expectations, choose distribution
channels, and watch those channels for adoption signals after release.

### Revealed preference on PyPI

The strongest form of evidence that a problem has an audience is that
somebody already built a tool for it and people download it.

| Library              | What it does                                | Monthly downloads | Direction |
|----------------------|---------------------------------------------|-------------------|-----------|
| `python-frontmatter` | Parse YAML frontmatter + markdown body      | ~6.85M            | Both (narrow slice) |
| `markdown-mdantic`   | Render Pydantic BaseModel as markdown table | ~5.3K             | One-way   |
| `docdantic`          | Generate Markdown API docs from Pydantic    | ~760              | One-way   |
| `pydantic-settings-export` | Markdown docs from `pydantic-settings`| modest            | One-way   |
| `settings-doc`       | Markdown docs from `BaseSettings`, Jinja-driven | modest        | One-way   |
| `funkyprompt`        | "Markdown-agent" framework mapping Pydantic ↔ markdown | ~48     | Partial, niche |

Two patterns in the numbers:

1. **There is a real audience for "Pydantic → markdown in some form."**
   Five distinct libraries exist. The most active (`markdown-mdantic`)
   gets thousands of monthly downloads — not huge, but real engineering
   time invested, not toy projects.
2. **Nobody has shipped typed round-trip.** Every library above is
   either one-way (model → markdown) or restricted to frontmatter. The
   one project that reaches for the full round-trip pattern
   (`funkyprompt`, built by the author of the "Rise of the Markdown
   Agent" Medium essay) has essentially no adoption.

For comparison, the JSON-structured-output cousin `instructor` gets
~10.6M downloads/month. The markdown-shaped niche is ~2000× smaller.

### LangChain and LangChain.js issue trackers

LangChain is the largest Python LLM application framework. When users
hit tool-shaped pain, they file issues.

- [**langchain-ai/langchain #11410**](https://github.com/langchain-ai/langchain/issues/11410)
  — "Feature: Markdown list output parser." The requester argued "most
  of the lists generated by LLMs are Markdown lists" and submitted a
  PR the same day. LangChain accepted it. The result (the
  `MarkdownListOutputParser`) handles only lists — the narrower case
  of what we built.
- [**langchain-ai/langchainjs #8068**](https://github.com/langchain-ai/langchainjs/issues/8068)
  — "Make JsonOutputParser able to extract JSON from markdown output."
  Adjacent pain: LLMs wrap JSON in markdown fences, and users file
  issues asking the JSON parser to be markdown-aware. Shows that the
  interaction between JSON and markdown in LLM output is common enough
  to generate tooling demands.
- [**langchain-ai/langchain #1600** (RouterOutputParser)](https://github.com/hwchase17/langchainjs/issues/1600)
  — User reporting that the existing parser fails on LLM-generated
  markdown. Yet another "parse markdown reliably" failure mode.

None of these asks quite matches what this package offers — but each
one is evidence that markdown parsing is a real pain surface in the
most-used framework. The step from `MarkdownListOutputParser` to "a
full typed markdown document parser" is natural.

### n8n community forum

n8n is a workflow automation platform whose users increasingly wire in
LLMs; they hit LLM output formatting pain without being ML engineers.

- [**"Get consistent, well-formatted Markdown/JSON outputs from LLMs"**](https://community.n8n.io/t/get-consistent-well-formatted-markdown-json-outputs-from-llms/80749)
  — A user asks how to get reliable markdown (and JSON) output from
  LLMs. Responders recommend regex cleaning and prompt engineering —
  i.e., scripting around the absence of a better tool. One contributor
  mentions schema validation with auto-fixing parsers as the more
  robust approach, but notes n8n's support for this remains limited.

This is a useful datapoint: people outside the ML-tooling bubble are
asking for exactly the thing the package does, and are finding only
workarounds.

### Hacker News practitioner discussion

The Hacker News thread ["Every Way to Get Structured Output from LLMs"](https://news.ycombinator.com/item?id=40713952)
(discussion of Boundary ML's BAML post) surfaced two independent
practitioners making arguments that support the package's premise:

- One commenter: *"Markdown is machine-readable enough for
  post-processing and easy output format for LLMs … I give the structure
  (a list of headings) for the LLM, which conforms to them 100% of the
  time."* This is effectively a one-paragraph description of the
  agent-foundry markdown package's core technique — arrived at
  independently.
- Another commenter: *"Enforcing a JSON format on output generally
  lowered the quality of the results."* A quality-motivated argument
  for preferring markdown over JSON as the LLM target format.

Neither of these is an endorsement of a specific library, but they
validate that thoughtful practitioners are reaching the same conclusion
about markdown as a structured-output format.

### Practitioner writing and independent builders

- [**"Rise of the Markdown Agent"**](https://medium.com/@mrsirsh/rise-of-the-markdown-agent-89b20d61c704)
  — Sirsh Amarteifio's Medium essay articulates "Object Oriented
  Generation": use Pydantic in code, render as markdown for LLMs. The
  author's accompanying library, `funkyprompt`, attempts the full
  pattern; it's under-adopted but its existence is evidence that
  builders outside Agent Foundry are arriving at the same design.
- [**Pydantic AI's "Stream markdown" example**](https://ai.pydantic.dev/examples/stream-markdown/)
  — Pydantic's own AI framework ships an example specifically for
  streaming markdown output, acknowledging markdown as a first-class
  LLM output format. (The example streams to Rich, it does not
  validate against a typed schema — again, the round-trip case is
  unserved.)
- [**BAML**](https://github.com/BoundaryML/baml) — Boundary ML's
  schema-first structured-output DSL treats markdown as *noise inside
  LLM JSON output* (its "Schema-Aligned Parsing" strips markdown code
  fences around JSON). Useful counter-evidence: BAML's design position
  is "markdown is wrapper cruft around JSON," not "markdown is the
  document format." Different worldview.

### What the signals don't say

Important counter-evidence to track honestly:

- **Ecosystem convergence is on JSON, not markdown.** Native
  structured output from OpenAI, Anthropic, and Google uses JSON
  Schema enforcement at decoding time. `instructor`'s scale (~10.6M
  downloads/month) dwarfs anything in the markdown niche. Markdown-as-
  structured-format is a minority position.
- **No viral pain post.** We did not find a thousand-upvote HN or
  Reddit thread demanding this specific library. The demand is
  distributed and quiet, expressed as individual issues and individual
  blog posts.
- **The n8n workaround path (regex + prompt tuning) is the default
  response.** Many users will script around the problem rather than
  adopt a new library.

### What this means for the launch plan

- **Realistic initial audience: hundreds to low thousands of
  builders.** Not mass-market. Plan distribution accordingly — a blog
  post, a PyPI release, and cross-posts into the Pydantic community
  and LLM-tooling channels will reach the relevant audience.
- **Best distribution channels** (in descending signal-to-noise):
  1. Pydantic GitHub Discussions and Discord
  2. LangChain issue tracker (as a suggested third-party parser)
  3. LLM-tooling HN/Reddit threads where the pain already surfaces
  4. Medium / dev.to posts framing the use case concretely
- **Name choice matters less than usually thought.** The audience is
  small enough that anyone who needs this will find it by following
  links from LangChain issues or HN threads, regardless of package
  name.
- **Post-release watch list.** Monthly downloads of
  `markdown-mdantic` and `python-frontmatter` set the ceiling; if this
  package does not approach `markdown-mdantic`'s scale within a year,
  the hypothesis (round-trip is the unmet need) is probably wrong and
  we should revisit.

---

## How To Use It

### Core concept

A template is a `MarkdownDocument` or `MarkdownHeader` subclass with typed
Pydantic fields. Each body field carries a role annotation that tells the
engine how to render and parse that field. The class name becomes the
title; `snake_case` field names become Title-Case headings.

### Minimal example

```python
from typing import Annotated
from agent_foundry.markdown import (
    MarkdownDocument, MarkdownHeader, AsHeading,
    render_template, render_instance, validate_markdown,
)

class Review(MarkdownDocument):
    title: str
    summary: Annotated[str, AsHeading()]

# 1. Render the empty skeleton (for handing to an LLM as instructions):
print(render_template(Review))
# # <!-- Review title -->
#
# ## Summary
#
# <!-- field body -->

# 2. Render a populated instance:
populated = Review(title="Q4 audit", summary="All systems nominal.")
print(render_instance(populated))

# 3. Parse markdown back into a validated instance:
doc = validate_markdown(markdown_text, Review)
```

### Fuller example exercising every annotation

```python
from typing import Annotated
from pydantic import BaseModel
from agent_foundry.markdown import (
    MarkdownDocument, MarkdownHeader,
    AsHeading, AsCodeBlock, AsBulletList, AsNumberedList, AsTable,
    TextTemplate,
)

class Metadata(BaseModel):
    change_set: str
    commit_range: str

class Row(BaseModel):
    path: str
    status: str

class Finding(MarkdownHeader):
    title: Annotated[str, TextTemplate("Finding {ordinal} - {value}")]
    code: Annotated[str, AsCodeBlock(language="python")]
    tags: Annotated[list[str], AsBulletList()]
    description: Annotated[str, AsHeading()]

class ReviewerOutput(MarkdownDocument):
    frontmatter: Metadata | None = None
    title: Annotated[str, TextTemplate("{value}")]
    next_steps: Annotated[list[str], AsNumberedList()]
    files: Annotated[list[Row], AsTable()]
    summary: Annotated[str, AsHeading()]
    findings: list[Finding]
```

A `ReviewerOutput` instance round-trips through markdown without information
loss: `validate_markdown(render_instance(x), ReviewerOutput) == x`.

### Extracting a subtree

When a document produced by one agent contains a section another agent should
parse against a smaller schema, `extract_subtree` pulls that section out and
rebases its heading levels:

```python
from agent_foundry.markdown import extract_subtree, validate_markdown

section_md = extract_subtree(
    full_doc,
    heading_level=2,
    title_match="Summary",
)
summary = validate_markdown(section_md, SummaryTemplate)
```

### Error model

All failures raise a subclass of `MarkdownError`:

- `MarkdownTemplateError` — raised at *class definition time* when a
  template subclass violates a structural rule (missing `title`, wrong
  body-field order, incompatible annotation/type pairing, frontmatter
  placement). This fires from `__pydantic_init_subclass__`, so malformed
  templates are caught at import, not at runtime.
- `MarkdownValidationError` — raised when markdown text does not match
  its template (missing required heading, mismatched order, frontmatter
  YAML error).
- `MarkdownExtractionError` — raised when `extract_subtree` cannot find
  a unique matching heading.
- `MarkdownError` — common base for `except MarkdownError:` catch-alls.

---

## Potential Enhancements

Ordered roughly by the payoff / cost ratio. The ADR at
`docs/architecture/adr_markdown_template_model_shape.md` already names the
first three as planned Phase 2+ work.

### High-value, ADR-planned

1. **Instruction-appendix generation.** Derive a structured prompt appendix
   from field descriptions and annotations — "For field `summary`, write …"
   — so products can hand the appendix to an LLM alongside the skeleton
   template. This is where the Pydantic-as-canonical-template design pays
   off the most: one declaration, three artifacts (skeleton, instructions,
   validator).

2. **`to_claude_code_schema` integration.** The sibling
   `agent_foundry.agents.schema_tools` module already transforms a
   Pydantic JSON schema into a form Claude Code accepts via `--json-schema`
   (inlines `$defs`/`$ref`, strips OpenAPI `discriminator`). Either
   absorb that utility into this package as a fourth public operation
   (`to_structured_output_schema(model)`) or publish it as a companion
   package — both are small and share an audience.

3. **Semantic validation hook.** Run an LLM-as-judge step against a
   populated instance to check that each field's content actually
   satisfies the field's description. Output would be a report of
   per-field verdicts, not a boolean — products decide how to act on it.

### Addressing explicit Phase 1 limitations

4. **Nested lists.** `MarkdownBulletList` / `MarkdownNumberedList`
   currently flatten to `list[str]`. Recursive nesting is a natural
   extension and is already a known limitation (`elements.py` docstrings:
   "nested lists are not supported in Phase 1").

5. **Rich inline content in table cells.** `MarkdownTableRow.cells` is
   `list[str]`; rich inline (bold, italic, links, inline code) is flattened.
   Preserving inline structure would widen the set of documents that
   round-trip losslessly.

6. **Multiple-match support in `extract_subtree`.** Currently raises on
   more than one match. Either (a) expose an iterator variant, or
   (b) take an optional `occurrence: int` parameter, or
   (c) take a path of (level, text) pairs for disambiguation.

7. **`AsHeading` parameters.** Phase 1 has no options. Candidates:
   explicit heading text override (rather than snake-case conversion),
   optional heading-text-field linkage for computed headings, collapsed
   (detail block) rendering.

### Broader API extensions

8. **`AsRawMarkdown` annotation.** Escape hatch for fields whose content
   is arbitrary markdown that should pass through verbatim — useful when
   the content itself was produced by another declarative template and
   nesting is inconvenient.

9. **Custom annotation registration.** Let application authors define
   their own role annotations with a `register_annotation(cls, renderer,
   parser)` API, so the set of recognized roles is open for extension
   rather than closed to the six built-ins.

10. **Pluggable markdown parser.** `markdown-it-py` is the only supported
    backend. A protocol-based adapter layer would let people swap in
    Mistune or Marko (e.g., if they want pluggable GFM extensions the
    `markdown-it-py` Python port doesn't have).

11. **Non-Pydantic template support (attrs, dataclasses).** The core
    mechanism depends on Pydantic's `model_fields`, `model_json_schema`,
    and `model_validate`. A thin adapter could let attrs / dataclass
    users declare templates without pulling Pydantic — though this
    would cost significant complexity and may not be worth it.

### Developer ergonomics

12. **Mypy / Pyright plugin or stubs.** Field metadata is inferred via
    reflection; static type checkers do not understand the bridge from
    `Annotated[str, AsHeading()]` to "this field becomes a heading." A
    plugin could surface template validation errors in the editor before
    the class is even imported.

13. **CLI for template inspection.** `python -m typemark describe
    my_module:Review` prints the rendered skeleton, the JSON schema, and
    the meta-validation report. Handy for debugging agent prompts.

14. **Error messages that show the failing span.** `MarkdownValidationError`
    messages today are field-localized. Adding a line-column hint plus the
    offending markdown excerpt would shorten the debug loop when an LLM
    produces slightly-malformed output.

15. **Property-based tests via Hypothesis.** The round-trip invariant
    (`validate_markdown(render_instance(x), T) == x`) is a natural fit
    for property-based testing. The test suite has hand-written
    round-trip tests; Hypothesis would widen coverage cheaply.

### Documentation and release

16. **Hosted docs (mkdocs / sphinx).** The current ADR lives in this
    repo; public users need a site. A `docs/` directory with the
    quickstart, annotation reference, recipes, and migration notes is
    the minimum for a credible 0.1 release.

17. **Annotated changelog + semver policy.** The ADR mentions phases;
    a public changelog would map phases to releases and make the
    compatibility contract explicit.

---

## Migration Steps

A conservative sequence; each step is a small, reviewable change.

### Step 0 — Decisions to make before coding

- **Package name.** Working list:
  - `typemark` — compact, type + markdown
  - `mdtemplate` — descriptive, longer
  - `pydantic-markdown` — obvious but couples the brand
  - `markdown-schema` — emphasises the validation angle

  PyPI availability must be checked for whichever name is chosen.
- **Module path.** Likely `import typemark` with the existing layout
  preserved underneath.
- **License.** This repo is MIT. Extraction should keep MIT unless
  there is a specific reason to change.
- **Copyright / authorship.** Decide whether the new repo attributes
  copyright to Mark Norman individually, to an umbrella project, or to
  a future org. This affects the `LICENSE` file and `pyproject.toml`'s
  `[project.authors]`.
- **In-repo shim vs. clean cut.** Two options for the agent_foundry side:
  1. Delete `src/agent_foundry/markdown/` entirely and add the new
     package as a dependency. Clean, but future Agent Foundry consumers
     pick up an external dep immediately.
  2. Keep a thin re-export shim at `agent_foundry.markdown` that
     imports everything from the new package. Zero import-path churn
     for any future in-repo consumer.

  Recommend option 1 — there are no in-repo consumers to break, and the
  whole point is public availability.

### Step 1 — Create the new repo

- Initialize a fresh git repo on GitHub with a chosen name.
- Add `LICENSE` (MIT), `README.md` skeleton, `.gitignore` (Python),
  `.pre-commit-config.yaml` mirroring this repo's.
- Add a `pyproject.toml` using PDM (to keep tooling parity with
  agent_foundry) with:
  ```toml
  dependencies = [
      "pydantic>=2.12.5",
      "markdown-it-py>=4.0.0",
      "pyyaml>=6.0.3",
  ]
  requires-python = ">=3.12"
  ```
  Note: relax the interpreter floor from `==3.14.*` to `>=3.12`
  (3.14 is what Agent Foundry pins; a library should support more).
  Audit the package for 3.14-only syntax — there shouldn't be any,
  but verify.

### Step 2 — Copy the code

- Copy `src/agent_foundry/markdown/` → `src/<new_name>/` (or
  `src/typemark/` if that's the chosen name), preserving internal
  structure.
- Copy `tests/agent_foundry/markdown/` → `tests/<new_name>/`, including
  the `fixtures/` directory.
- Mechanical rename pass: every occurrence of
  `agent_foundry.markdown` → `<new_name>`. This is a single
  `sed` / editor-wide find-replace touching ~25 import lines in
  source and ~40 import lines in tests.
- Update docstrings that reference the ADR path:
  `agent-foundry/docs/architecture/adr_markdown_template_model_shape.md`
  → a link to a copy of the ADR in the new repo's `docs/` directory
  (or to the ADR's GitHub URL in the agent_foundry repo if preserving
  the original location).

### Step 3 — Set up CI

- GitHub Actions workflow running `pytest`, `ruff check`, `pyright` (or
  `mypy`) on pushes and PRs against Python 3.12, 3.13, 3.14.
- Optional: publish coverage to Codecov or similar.

### Step 4 — Write the README

Minimum sections:
- What it is (the one-line pitch)
- Install / quickstart
- Core concepts (MarkdownDocument, MarkdownHeader, annotations)
- Full worked example (port from the ADR or this document)
- Error model
- Status + stability note (honest about Phase 1 limits)
- License + contributing pointer

### Step 5 — Version tag and publish

- `pdm version 0.1.0` (or 0.0.1 if pre-1.0 signalling is preferred).
- `pdm build`
- `pdm publish` to PyPI (after verifying the name is available).

### Step 6 — Remove from agent_foundry

- Delete `src/agent_foundry/markdown/` and `tests/agent_foundry/markdown/`.
- Add the new package as a dependency in `agent-foundry/pyproject.toml`.
- Any future in-repo consumer imports from the new name. No shim.
- Commit as a single "chore(markdown): extract to public package" change.

### Step 7 — Announce

- Short blog post or README cross-link in agent_foundry.
- Cross-post to the Pydantic community (Discord / GitHub Discussions)
  and relevant Python-LLM channels — this is the audience that
  immediately benefits.

### Migration effort estimate

- Steps 1-4: ~2–3 hours of focused work.
- Step 5: ~30 minutes once the PyPI name is sorted.
- Step 6: ~30 minutes.
- Step 7: as much or as little as desired.

Total: **a half-day's work**, none of it risky.

---

## Open Questions

_To be filled in as we iterate on this plan._

- Package name?
- Single-repo release or start as a monorepo with a companion package
  (e.g., the Claude Code schema helpers)?
- Semver policy pre-1.0?
- Who is the maintainer of record?
- Does Archipelago adopt the package before or after the extraction?

---

## Appendix — Stats

- Source: 12 files, ~1,570 LOC
- Tests: 12 test files + fixtures, ~1,262 LOC
- Dependencies (runtime): `pydantic`, `markdown-it-py`, `pyyaml`
- In-repo consumers (non-test): 0
- Git history: ~25 commits, all under `feat(markdown)` / `fix(markdown)` /
  `refactor(markdown)` prefixes
- Phase 1 committed: 2026-04-19 (same day as this document)
- Governing ADR: `docs/architecture/adr_markdown_template_model_shape.md`
