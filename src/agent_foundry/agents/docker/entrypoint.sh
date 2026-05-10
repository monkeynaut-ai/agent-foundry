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

# ── Supplementary GIDs ──
# When SUPPLEMENTARY_GIDS is set (comma-separated numeric GIDs), add the
# claude user to those groups before gosu drops privileges. This is the
# only correct hook: the Docker exec API does not support GroupAdd, so
# group membership must be configured at container startup.
if [ -n "$SUPPLEMENTARY_GIDS" ]; then
  for gid in $(echo "$SUPPLEMENTARY_GIDS" | tr ',' ' '); do
    # Create the group if it doesn't exist in /etc/group.
    getent group "$gid" >/dev/null 2>&1 || groupadd -g "$gid" "group_${gid}"
    # Resolve the group name (usermod -aG requires a name, not a GID).
    gname=$(getent group "$gid" | cut -d: -f1)
    usermod -aG "$gname" claude
  done
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

# ── Interactive/headless fallback ──
if [ -t 0 ]; then
  exec gosu claude /home/claude/.local/bin/claude "$@"
else
  exec gosu claude /home/claude/.local/bin/claude -p "$@"
fi
