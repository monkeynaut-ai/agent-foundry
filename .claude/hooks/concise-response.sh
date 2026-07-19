#!/bin/bash
# Injects concise-response rules into every model turn via additionalContext.
# Configured as a UserPromptSubmit hook.

cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "Apply these rules to your response:

- Be concise by default. Expand only when the user asks.
- Use plain language appropriate to the domain being discussed.
- Remove introductions, repetition, and generic closing offers.
  }
}
EOF
