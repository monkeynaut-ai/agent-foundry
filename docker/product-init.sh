#!/bin/sh
# Archipelago product initialization — runs inside the container at startup.
# Sourced by the ACP base entrypoint via product-init.sh hook.
#
# Note: Pyright LSP plugin installation is now handled by the base image entrypoint.

# Check for Claude Code updates and notify via protocol.
INSTALLED=$(/home/claude/.local/bin/claude --version 2>/dev/null || echo "unknown")
LATEST=$(curl -sf --max-time 10 https://registry.npmjs.org/@anthropic-ai/claude-code/latest | jq -r .version 2>/dev/null || echo "unknown")

if [ "$INSTALLED" != "unknown" ] && [ "$LATEST" != "unknown" ] && [ "$INSTALLED" != "$LATEST" ]; then
  echo "ARCHIPELAGO_UPDATE_AVAILABLE {\"installed\": \"$INSTALLED\", \"latest\": \"$LATEST\"}"
fi
