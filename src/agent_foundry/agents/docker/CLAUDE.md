# Agent Worker

You are an agent running in a sandboxed container. Your task is delivered as a prompt; additional role-specific instructions may be appended to this file at container startup.

- **Work in `/workspace`** — do not modify files outside it.
- Additional context files (`CLAUDE-*.md`) in this directory, if present, apply to your specific role.

## Communication protocol

You return results via **structured output**. The host invokes you with a JSON schema (`--json-schema`); you respond by calling the `StructuredOutput` tool exactly once, with a payload matching the schema. The payload is an `AgentTurnEnvelope` with one of four outcomes:

- `success` — task completed, payload contains your result.
- `clarification_needed` — blocked on a question; payload states what you need.
- `permission_needed` — blocked on an action outside your grant; payload states the action and why.
- `failed` — unrecoverable; payload contains `reason`.

Emit the `StructuredOutput` tool call as your final action every turn. Do not rely on free-text signals; the host reads only the structured payload.

## LSP-first code navigation

You have a Pyright LSP server available. Prefer LSP over Grep/Read for:
- Finding references, definitions, implementations
- Hovering for types, listing document or workspace symbols
- Tracing incoming/outgoing calls
- Checking diagnostics after edits

Fall back to Grep/Read only when LSP has no server for the file type.

## lessons-learned skill

When your task completes, invoke the `lessons-learned` skill to log specific, actionable, non-obvious observations to `/workspace/documents/lessons-learned.md`.
