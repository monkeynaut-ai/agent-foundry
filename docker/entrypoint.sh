#!/bin/sh
set -e

# Validate authentication — require exactly one auth method
if [ -n "$CLAUDE_CODE_OAUTH_TOKEN" ] && [ -n "$ANTHROPIC_API_KEY" ]; then
  echo "ERROR: Both CLAUDE_CODE_OAUTH_TOKEN and ANTHROPIC_API_KEY are set." >&2
  echo "Set exactly one to avoid authentication conflicts." >&2
  exit 1
fi

if [ -z "$CLAUDE_CODE_OAUTH_TOKEN" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "ERROR: No authentication configured." >&2
  echo "Set CLAUDE_CODE_OAUTH_TOKEN (subscription) or ANTHROPIC_API_KEY (API billing)." >&2
  exit 1
fi

# Check for Claude Code updates and notify via PTY protocol.
# This is non-blocking — the container proceeds with the installed version
# regardless. Agent Foundry handles image rebuild if needed.
INSTALLED=$(/home/claude/.local/bin/claude --version 2>/dev/null || echo "unknown")
LATEST=$(curl -sf https://registry.npmjs.org/@anthropic-ai/claude-code/latest | jq -r .version 2>/dev/null || echo "unknown")

if [ "$INSTALLED" != "unknown" ] && [ "$LATEST" != "unknown" ] && [ "$INSTALLED" != "$LATEST" ]; then
  echo "ARCHIPELAGO_UPDATE_AVAILABLE {\"installed\": \"$INSTALLED\", \"latest\": \"$LATEST\"}"
fi

# Disable ICRNL so programmatic \r reaches Ink as \r (not converted to \n).
# Without this, the PTY line discipline converts \r → \n, and Ink's
# parse-keypress never sees 'return', so submit never fires.
stty -icrnl 2>/dev/null || true

# If a TTY is attached, run interactively; otherwise run headless
if [ -t 0 ]; then
  exec /home/claude/.local/bin/claude "$@"
else
  exec /home/claude/.local/bin/claude -p "$@"
fi
