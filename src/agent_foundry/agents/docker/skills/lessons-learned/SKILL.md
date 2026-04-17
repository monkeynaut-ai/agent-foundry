---
name: lessons-learned
description: Log lessons from the completed task to /workspace/.claude/lessons-learned.md
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash
---

Review this session and append useful lessons to `/workspace/.claude/lessons-learned.md`. A lesson is useful if
- it is clear when to use the lesson
- it is clear how to use the lesson
- the lesson has benefits. For example, reduces risk, increases correctness, increases coherence

## What to review

- **The task**: What was asked? Was the prompt clear? Were there ambiguities you had to resolve?
- **What you did**: What approaches did you take? What worked well? What didn't?
- **The information you were given**: Were you provided addtional information, such as a file to reference? Were there ambiguities you had to resolve? What information would have helped?
- **The capabilities available**: Were the tools, CLAUDE.md instructions, and working environment sufficient? Were there gaps?

## What counts as a lesson

Only log observations that would genuinely improve future sessions. Ask: would a future worker (or the human reviewing this log) find this useful? Good lessons are:

- Actionable: suggest a change to process, instructions, or tooling
- Non-obvious: not already covered by existing instructions

## Log format

Append to `/workspace/.claude/lessons-learned.md`. Create the file and the `.claude/` directory if they don't exist. Each entry must include a description of the lesson, when to use the lesson, how to apply the lesson, and the benefit of applying the lesson. Use the following format for each lesson:

```markdown
## YYYY-MM-DD — <lesson title>

### Description
### When to Use
### How to Apply
### Benefit
```

If there are no useful lessons, do not append anything. Do not create the file just to say "no lessons learned."
