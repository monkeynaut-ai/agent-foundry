#!/bin/bash
# Injects LSP-first reminder into every model turn via additionalContext.
# Configured as a UserPromptSubmit hook.

cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "LSP-FIRST RULE: Before using Grep, Read, or Glob for symbol navigation, use LSP tools. findReferences for call sites, goToDefinition for definitions, hover for type signatures, incomingCalls/outgoingCalls for call chains, workspaceSymbol for symbol search, documentSymbol for file inventory. Only fall back to Grep/Read when LSP has no server for the file type."
  }
}
EOF
