#!/bin/sh
set -e

# ── Authentication ──
# Require exactly one auth method
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

# ── Git credentials ──
if [ -n "$GITHUB_TOKEN" ]; then
  printf 'machine github.com\nlogin oauth2\npassword %s\n' "$GITHUB_TOKEN" > /home/claude/.netrc
  chmod 600 /home/claude/.netrc
fi

# ── Git identity ──
if [ -n "$GIT_USER_NAME" ]; then
  git config --global user.name "$GIT_USER_NAME"
fi
if [ -n "$GIT_USER_EMAIL" ]; then
  git config --global user.email "$GIT_USER_EMAIL"
fi

# ── Repo clone ──
# Clone into /workspace if REPO_URL is set and workspace is empty
if [ -n "$REPO_URL" ] && [ ! -d /workspace/.git ]; then
  git clone --branch "${REPO_REF:-main}" "$REPO_URL" /workspace
fi

# ── Product-specific init hook ──
# Source product init script if it exists (products drop this in via Dockerfile)
if [ -f /home/claude/product-init.sh ]; then
  . /home/claude/product-init.sh
fi

# ── Adapter launch ──
# ACP_WS_URL is the generic env var for adapter WebSocket connection.
# Also support ARCHIPELAGO_WS_URL for backward compatibility.
WS_URL="${ACP_WS_URL:-$ARCHIPELAGO_WS_URL}"

if [ -n "$WS_URL" ]; then
  TURN_TIMEOUT="${ACP_TURN_TIMEOUT:-${ARCHIPELAGO_TURN_TIMEOUT:-3600}}"
  SKIP_PERMS_FLAG=""
  if [ "${ACP_SKIP_PERMISSIONS:-${ARCHIPELAGO_SKIP_PERMISSIONS:-0}}" = "1" ]; then
    SKIP_PERMS_FLAG="--dangerously-skip-permissions"
  fi
  MARKER_CONFIG_FLAG=""
  if [ -f /home/claude/marker-config.json ]; then
    MARKER_CONFIG_FLAG="--marker-config /home/claude/marker-config.json"
  fi
  export PATH="/home/claude/.local/bin:$PATH"
  exec python /home/claude/adapter.py --protocol "$WS_URL" \
    --timeout "$TURN_TIMEOUT" $SKIP_PERMS_FLAG $MARKER_CONFIG_FLAG
fi

# ── Interactive/headless fallback ──
if [ -t 0 ]; then
  exec /home/claude/.local/bin/claude "$@"
else
  exec /home/claude/.local/bin/claude -p "$@"
fi
