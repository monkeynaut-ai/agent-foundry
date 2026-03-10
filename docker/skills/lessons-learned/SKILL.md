---
name: lessons-learned
description: Log observations and lessons from the completed task to /workspace/.claude/lessons-learned.md
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash
---

Review this session and append any useful lessons to `/workspace/.claude/lessons-learned.md`.

## What to review

- **The task**: What was asked? What was the feature spec, requirements, and test commands?
- **What you did**: What approaches did you take? What worked well? What didn't?
- **The information you were given**: Was the feature spec clear? Were there ambiguities you had to resolve? What information would have helped?
- **The capabilities available**: Were the tools, CLAUDE.md instructions, and working environment sufficient? Were there gaps?

## What counts as a lesson

Only log observations that would genuinely improve future sessions. Ask: would a future worker (or the human reviewing this log) find this useful? Good lessons are:

- Specific: tied to something concrete that happened, not generic advice
- Actionable: suggest a change to process, instructions, or tooling
- Non-obvious: not already covered by existing instructions

Skip lessons that are obvious, already documented, or too session-specific to generalize.

## Log format

Append to `/workspace/.claude/lessons-learned.md`. Create the file and the `.claude/` directory if they don't exist. Each entry:

```markdown
## YYYY-MM-DD — <task title or brief description>

- <lesson>
- <lesson>
```

If there are no useful lessons, do not append anything. Do not create the file just to say "no lessons learned."
