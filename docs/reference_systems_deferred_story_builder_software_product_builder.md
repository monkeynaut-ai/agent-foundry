# Reference Systems (Deferred): Story Builder + Software Product Builder

This document contains material moved out of the main build plan so the primary document focuses strictly on:
- the shared platform (Steps 1–6), and
- a single runnable reference demo: Decision Support.

---

## System A — Story/Narrative Builder
**Pattern:** Writers’ room + constraint checking + revision loop.

### Required state fields
- `story_bible` (facts, lore)
- `character_sheets`
- `outline`
- `draft`
- `continuity_issues`
- `style_report`
- `revision_notes`

### Recommended nodes/capabilities
- `rag_retriever` (retrieve story bible + prior chapters)
- `structured_output_pydantic` for:
  - Character sheet schema
  - Scene beat schema
- `llm_call_basic` (draft generation)
- `continuity_checker` (detect contradictions)
- `style_checker` (enforce voice)
- `draft_revision_loop` template
- `human_approval_gate` for major plot decisions

### Mandatory eval gates
- continuity validator
- style validator

---

## System C — Software Product Builder
**Pattern:** plan–execute–verify with strict gates.

### Required state fields
- `product_goal`
- `prd`
- `architecture`
- `task_breakdown`
- `repo_context`
- `code_changes`
- `test_results`
- `quality_reports`

### Recommended nodes/capabilities
- `structured_output_pydantic` for:
  - PRD outline
  - ADR format
  - Task list format
  - Change plan format
- `tool_calling` tools:
  - repo read/search
  - code edit
  - run tests
  - run lints
- `test_runner_gate`
- `static_analysis_gate`
- `definition_of_done_validator`
- `human_approval_gate` before merges/releases
- `plan_execute_test_fix_retest` template

### Mandatory eval gates
- tests must pass
- lint/static checks pass
- DoD validator pass

---

## Checklist Items (Deferred)
- Provide at least one `GraphWiringPlan` JSON for Story: character sheet + chapter draft + revise loop.
- Provide at least one `GraphWiringPlan` JSON for Software: PRD → ADR → tasks → implement → tests → fix → finalize.

