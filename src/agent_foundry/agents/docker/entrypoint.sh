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
. /home/claude/lockdown.sh

# ── Role-specific instructions ──
# Append role-specific content to CLAUDE.md rather than overwriting,
# so base-image and product-image instructions are preserved.
if [ -n "$AGENT_ROLE_INSTRUCTIONS_PATH" ] && [ -f "$AGENT_ROLE_INSTRUCTIONS_PATH" ]; then
  cat "$AGENT_ROLE_INSTRUCTIONS_PATH" >> /home/claude/.claude/CLAUDE.md
fi
echo "=== CLAUDE.md after role append ===" >&2
if [ -f /home/claude/.claude/CLAUDE.md ]; then
  cat /home/claude/.claude/CLAUDE.md >&2
  echo "=== end CLAUDE.md ===" >&2
else
  echo "ERROR: /home/claude/.claude/CLAUDE.md does not exist. The base image is malformed or was built incorrectly." >&2
  echo "=== end CLAUDE.md ===" >&2
  exit 1
fi

# ── LSP plugins ──
# Install language server plugins baked into the base image.
# Additional LSP servers will be added here as they're needed.
gosu claude claude plugin marketplace add anthropics/claude-plugins-official
gosu claude claude plugin install pyright-lsp@claude-plugins-official --scope user

# ── Host-driven mode ──
# When AGENT_HOST_DRIVEN=1 the container finishes setup and idles,
# waiting for `docker exec` calls from the host to invoke `claude`
# directly. Used by the Plan 2 host-driven executor, which runs each
# turn as `claude --resume <session-id> -p <prompt>` via exec_run.
#
# /tmp/.container-ready is the marker file consumed by the Dockerfile's
# HEALTHCHECK. Touching it here — AFTER all setup (auth, lockdown,
# role-instructions append, LSP plugin install) has finished — is the
# signal that the container is ready to receive work. Host-side code
# polls `container.attrs["State"]["Health"]["Status"]` until it reads
# ``healthy``.
if [ "${AGENT_HOST_DRIVEN:-0}" = "1" ]; then
  touch /tmp/.container-ready
  exec tail -f /dev/null
fi

# ── Adapter launch ──
if [ -n "$AGENT_WS_URL" ]; then
  TURN_TIMEOUT="${AGENT_TURN_TIMEOUT:-3600}"
  SKIP_PERMS_FLAG=""
  if [ "${AGENT_SKIP_PERMISSIONS:-0}" = "1" ]; then
    SKIP_PERMS_FLAG="--dangerously-skip-permissions"
  fi
  export PATH="/home/claude/.local/bin:$PATH"
  exec gosu claude python /home/claude/adapter.py --protocol "$AGENT_WS_URL" \
    --timeout "$TURN_TIMEOUT" $SKIP_PERMS_FLAG
fi

# ── Interactive/headless fallback ──
if [ -t 0 ]; then
  exec gosu claude /home/claude/.local/bin/claude "$@"
else
  exec gosu claude /home/claude/.local/bin/claude -p "$@"
fi
