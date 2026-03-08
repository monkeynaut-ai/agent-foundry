---
name: work-status
description: Update work-status.md to reflect current progress. Invoke when an item is completed, a new item is discovered, priorities shift, the user asks to update work status, or the user asks to add or remove an item.
allowed-tools: Read, Edit, Write
---

Keep `work-status.md` accurate and current.

## Current state
- File: !`cat work-status.md`

## Document structure

Sections appear in this order: **In Progress → Backlog → Completed**

## What to update

Read the current file and the session context, then make whatever changes are needed: move completed items to the Completed section (at the end) with a one-line decision note, update In Progress, add or reprioritize backlog items.

## Formatting rules

- All items carry a number — **numbers are immutable, never renumber or reuse them**
- New items use the number in `next item number:` at the bottom of the file; increment it after each use
- Completed items: numbered list, one-line decision note each
- Backlog items: `####` headings prefixed with their number, e.g. `#### 6. Add --dangerously-skip-permissions`
- **Heading text never changes** — anchor links depend on it; update content below the heading instead
- Never reference items by number in prose — use anchor links: `[title](#anchor-slug)`
- Anchor slugs: lowercase, spaces → hyphens, special characters stripped
