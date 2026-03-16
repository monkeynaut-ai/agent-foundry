#!/bin/sh
set -e

# This entrypoint runs as root to enforce filesystem lockdown, then drops
# to the claude user via gosu before launching the agent.

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
  chown claude:claude /home/claude/.netrc
fi

# ── Git identity ──
if [ -n "$GIT_USER_NAME" ]; then
  gosu claude git config --global user.name "$GIT_USER_NAME"
fi
if [ -n "$GIT_USER_EMAIL" ]; then
  gosu claude git config --global user.email "$GIT_USER_EMAIL"
fi

# ── Repo clone ──
# Ensure workspace is writable by claude before cloning
chown claude:claude /workspace
if [ -n "$REPO_URL" ] && [ ! -d /workspace/.git ]; then
  gosu claude git clone --branch "${REPO_REF:-main}" "$REPO_URL" /workspace
fi

# ── Filesystem lockdown ──
# Applied as root after clone, before dropping to claude user.
# ACP_HIDDEN_DIRS: comma-separated paths to make completely inaccessible (chmod 000)
# ACP_READONLY_DIRS: comma-separated paths to make read-only (chmod a-w recursive)
if [ -n "$ACP_HIDDEN_DIRS" ]; then
  IFS=',' ; for dir in $ACP_HIDDEN_DIRS; do
    [ -d "$dir" ] && chmod 000 "$dir"
  done; unset IFS
fi
if [ -n "$ACP_READONLY_DIRS" ]; then
  IFS=',' ; for dir in $ACP_READONLY_DIRS; do
    [ -d "$dir" ] && chmod -R a-w "$dir"
  done; unset IFS
fi

# ── Role-specific instructions ──
# Append role-specific content to CLAUDE.md rather than overwriting,
# so base-image and product-image instructions are preserved.
if [ -n "$ACP_ROLE_INSTRUCTIONS_PATH" ] && [ -f "$ACP_ROLE_INSTRUCTIONS_PATH" ]; then
  cat "$ACP_ROLE_INSTRUCTIONS_PATH" >> /home/claude/.claude/CLAUDE.md
fi

# ── LSP plugins ──
# Install language server plugins baked into the base image.
# Additional LSP servers will be added here as they're needed.
gosu claude claude plugin marketplace add anthropics/claude-plugins-official
gosu claude claude plugin install pyright-lsp@claude-plugins-official --scope user

# ── Product-specific init hook ──
# Source product init script if it exists (products drop this in via Dockerfile)
if [ -f /home/claude/product-init.sh ]; then
  gosu claude sh -c '. /home/claude/product-init.sh'
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
  exec gosu claude python /home/claude/adapter.py --protocol "$WS_URL" \
    --timeout "$TURN_TIMEOUT" $SKIP_PERMS_FLAG $MARKER_CONFIG_FLAG
fi

# ── Interactive/headless fallback ──
if [ -t 0 ]; then
  exec gosu claude /home/claude/.local/bin/claude "$@"
else
  exec gosu claude /home/claude/.local/bin/claude -p "$@"
fi
