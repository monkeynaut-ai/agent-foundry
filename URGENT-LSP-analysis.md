# URGENT: LSP Usage Analysis

## Problem

Claude Code is not following the LSP-first rule in CLAUDE.md despite clear instructions and a memory note reinforcing it.

## Why It Happens

### The instructions are clear but the incentives don't align

Read/Grep are faster, always work, and return immediate results. LSP requires knowing the exact file, line, and character position — which means I often need to Read the file first anyway just to find the position. So in practice, Read feels like the shorter path even when LSP would give more precise answers.

### The rule is broad but the payoff is situational

The CLAUDE.md says to use LSP *before* doing any of the listed operations. But for many tasks (like writing new code against known interfaces), LSP adds overhead without changing the outcome. The rule doesn't distinguish "analyzing existing code" from "writing new code that touches existing signatures."

### There's no feedback loop

Nothing stops or penalizes skipping LSP. The work still succeeds, tests pass, and the conversation moves forward. The memory note and CLAUDE.md instructions are easy to deprioritize under task pressure.

## Possible Approaches

1. **Narrow the rule** — instead of "always use LSP first," target the high-value cases: "Before changing any function signature, use `findReferences` to identify all callers." That's specific and auditable.

2. **Make it a checklist gate** — "Before committing, confirm you used `findReferences` on every modified function signature." The model would need to explicitly acknowledge it.

3. **Accept it may not stick via instructions alone** — this might be a genuine limitation of instruction-following under task load. The model optimizes for task completion, and LSP feels like friction when Read already worked.

## Session Evidence

In the March 4 2026 session fixing Docker worker bugs, LSP was not used at all. Places where it should have been used:

- Verifying `destroy()` callers before changing its signature (removing `remove_volume` param)
- Checking `create_container` call sites before removing the `repo_ref` param
- Confirming `persist_workspace_state` callers before adding new parameters
- Verifying `recover_session` callers before changing its internal behavior
