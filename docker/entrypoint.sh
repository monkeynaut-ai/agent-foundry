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

# Write git credentials to .netrc for the container's lifetime.
# GITHUB_TOKEN is forwarded from the host via DEFAULT_ENV_ALLOWLIST.
# All git operations (clone, push, pull) use this automatically.
if [ -n "$GITHUB_TOKEN" ]; then
  printf 'machine github.com\nlogin oauth2\npassword %s\n' "$GITHUB_TOKEN" > /home/claude/.netrc
  chmod 600 /home/claude/.netrc
fi

# Clone the repo into /workspace if REPO_URL is set and workspace is not already populated.
# Skipped when the workspace volume already has a repo (shared volume, subsequent nodes,
# or crash recovery).
if [ -n "$REPO_URL" ] && [ ! -d /workspace/.git ]; then
  git clone --branch "${REPO_REF:-main}" "$REPO_URL" /workspace
fi

# Check for Claude Code updates and notify via protocol.
# This is non-blocking — the container proceeds with the installed version
# regardless. Agent Foundry handles image rebuild if needed.
INSTALLED=$(/home/claude/.local/bin/claude --version 2>/dev/null || echo "unknown")
LATEST=$(curl -sf https://registry.npmjs.org/@anthropic-ai/claude-code/latest | jq -r .version 2>/dev/null || echo "unknown")

if [ "$INSTALLED" != "unknown" ] && [ "$LATEST" != "unknown" ] && [ "$INSTALLED" != "$LATEST" ]; then
  echo "ARCHIPELAGO_UPDATE_AVAILABLE {\"installed\": \"$INSTALLED\", \"latest\": \"$LATEST\"}"
fi

# If adapter WS URL is set, run via headless protocol adapter
if [ -n "$ARCHIPELAGO_WS_URL" ]; then
  exec python /home/claude/adapter.py --protocol "$ARCHIPELAGO_WS_URL"
fi

# If a TTY is attached, run interactively; otherwise run headless
if [ -t 0 ]; then
  exec /home/claude/.local/bin/claude "$@"
else
  exec /home/claude/.local/bin/claude -p "$@"
fi
