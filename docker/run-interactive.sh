#!/bin/bash
# Start an interactive shell in the archipelago-cc-worker container.
# Requires ANTHROPIC_API_KEY in the host environment.
#
# Usage: ./run-interactive.sh [-i IMAGE]
#
# Options:
#   -i IMAGE   Docker image to run (default: archipelago-cc-worker:latest)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="archipelago-cc-worker:latest"

while getopts "i:" opt; do
  case $opt in
    i) IMAGE="$OPTARG" ;;
    *) echo "Usage: $0 [-i IMAGE]" >&2; exit 1 ;;
  esac
done

# Load .env from project root if ANTHROPIC_API_KEY is not already set
if [ -z "$ANTHROPIC_API_KEY" ] && [ -f "$SCRIPT_DIR/../.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "ERROR: ANTHROPIC_API_KEY is not set and no .env file found." >&2
  exit 1
fi

ENV_ARGS=(-e "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY")
for var in GITHUB_TOKEN GIT_USER_NAME GIT_USER_EMAIL; do
  if [ -n "${!var}" ]; then
    ENV_ARGS+=(-e "$var=${!var}")
  fi
done

docker run -it --rm \
  "${ENV_ARGS[@]}" \
  "$IMAGE"
