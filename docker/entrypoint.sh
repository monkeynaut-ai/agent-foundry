#!/bin/sh
set -e

# Check for Claude Code updates and notify via PTY protocol.
# This is non-blocking — the container proceeds with the installed version
# regardless. Agent Foundry handles image rebuild if needed.
INSTALLED=$(claude --version 2>/dev/null || echo "unknown")
LATEST=$(curl -sf https://registry.npmjs.org/@anthropic-ai/claude-code/latest | jq -r .version 2>/dev/null || echo "unknown")

if [ "$INSTALLED" != "unknown" ] && [ "$LATEST" != "unknown" ] && [ "$INSTALLED" != "$LATEST" ]; then
  echo "ARCHIPELAGO_UPDATE_AVAILABLE {\"installed\": \"$INSTALLED\", \"latest\": \"$LATEST\"}"
fi

# Execute claude in headless mode with any passed arguments
exec claude -p "$@"
