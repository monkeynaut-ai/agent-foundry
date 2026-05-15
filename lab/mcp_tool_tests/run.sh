#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

cd "$REPO_ROOT"
PYTHONPATH="$REPO_ROOT/src" pdm run pytest \
    "$SCRIPT_DIR" \
    -m integration \
    -v -s \
    -p no:xdist \
    --override-ini="addopts=" \
    "$@"
