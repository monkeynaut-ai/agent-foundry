#!/usr/bin/env bash
# Smoke-test the codex subscription-auth bind-mount pattern.
#
# Prerequisites:
#   1. Run `codex login` on the host to create ~/.codex/auth.json.
#   2. Build the test image:
#        docker build -t agent-foundry-codex-cohabit-test:latest \
#          -f src/agent_foundry/agents/docker_v2/Dockerfile.codex-cohabit-test .
#
# What this verifies:
#   - The bind mount of ~/.codex/auth.json into the container works.
#   - codex inside the container authenticates against ChatGPT subscription
#     (no OPENAI_API_KEY env, file-based OAuth only).
#   - codex exec produces a structured response, exit 0.
#
# Failure modes this catches:
#   - Mount path wrong / file not visible inside container.
#   - File-permission rejection (codex refusing to read ro mount).
#   - codex misinterpreting the auth file format inside the container.
#   - OAuth token expired (host needs `codex login` refresh).

set -euo pipefail

IMAGE="${IMAGE:-agent-foundry-codex-cohabit-test:latest}"
HOST_AUTH="${AGENT_FOUNDRY_CODEX_AUTH_PATH:-$HOME/.codex/auth.json}"
CONTAINER_AUTH="/home/claude/.codex/auth.json"

if [ ! -f "$HOST_AUTH" ]; then
  echo "FAIL: $HOST_AUTH does not exist. Run 'codex login' on the host first." >&2
  exit 1
fi
if [ ! -r "$HOST_AUTH" ]; then
  echo "FAIL: $HOST_AUTH exists but is not readable by current user." >&2
  exit 1
fi

# Create a sanitized copy of auth.json with OPENAI_API_KEY stripped, to
# guarantee the in-container test exercises OAuth tokens only (not a
# fallback to the embedded API key). The original host file is not
# modified.
SANITIZED=$(mktemp -t codex-auth-oauth-only.XXXXXX.json)
trap 'rm -f "$SANITIZED"' EXIT

python3 -c "
import json, sys
with open('$HOST_AUTH') as f:
    data = json.load(f)
removed_api_key = data.pop('OPENAI_API_KEY', None)
has_tokens = 'tokens' in data and 'access_token' in data.get('tokens', {})
if not has_tokens:
    print('FAIL: auth.json has no OAuth tokens. Run \`codex login\` (interactive) on the host.', file=sys.stderr)
    sys.exit(1)
with open('$SANITIZED', 'w') as f:
    json.dump(data, f)
print('Sanitized copy ready: OPENAI_API_KEY stripped, OAuth tokens retained.')
"

echo "=== Mounting $SANITIZED (OAuth-only) -> $CONTAINER_AUTH ==="

# Explicitly unset OPENAI_API_KEY env so env-var auth can't satisfy the
# test either. The container must use file-based OAuth or fail.
docker run --rm \
  -v "$SANITIZED:$CONTAINER_AUTH:ro" \
  --env "OPENAI_API_KEY=" \
  --entrypoint sh \
  "$IMAGE" \
  -c '
    set -e
    echo "--- file visible inside container ---"
    ls -la /home/claude/.codex/auth.json
    echo "--- OPENAI_API_KEY (should be empty) ---"
    echo "OPENAI_API_KEY=[${OPENAI_API_KEY}]"
    echo "--- codex login status (should report ChatGPT) ---"
    codex login status
    echo "--- codex exec ---"
    codex exec --json --skip-git-repo-check -o /tmp/last.txt "reply with a single short greeting" < /dev/null
    echo "--- last message ---"
    cat /tmp/last.txt
  '

echo
echo "PASS — codex authenticated via OAuth-only auth.json (no API key) and returned a response."
