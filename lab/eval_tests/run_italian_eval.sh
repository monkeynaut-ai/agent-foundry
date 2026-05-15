#!/usr/bin/env bash
#
# Run the Italian-word classifier eval suite.
#
# Defaults match Agent Foundry's integration-test conventions:
#   * Base image: agent-worker:latest (build via `pdm docker-base`).
#   * Workspace volume: a fresh, uniquely-named Docker volume per run.
#   * Artifacts directory: ./lab/eval_tests/.artifacts/<timestamp>/
#   * Report output: ./lab/eval_tests/.runs/
#
# Override any default via env vars:
#   AGENT_BASE_IMAGE=my-image:tag
#   WORKSPACE_VOLUME=my-volume-name
#   ARTIFACTS_DIR=/some/path
#   OUT_DIR=/some/other/path
#
# Extra args after `--` are forwarded to the eval CLI:
#   ./run_italian_eval.sh -- --max-concurrency 4 --invocations 3
#
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
REPO_ROOT="$( cd "${SCRIPT_DIR}/../.." && pwd )"
SUITE="${SCRIPT_DIR}/italian_word_suite.py"

if [[ ! -f "${SUITE}" ]]; then
    echo "error: suite file not found: ${SUITE}" >&2
    exit 1
fi

# Load the repo-root .env if present so users can keep secrets there
# (e.g. CLAUDE_CODE_OAUTH_TOKEN) instead of exporting them every shell.
ENV_FILE="${REPO_ROOT}/.env"
if [[ -f "${ENV_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
fi

# The agent containers' entrypoint requires Claude Code authentication
# via CLAUDE_CODE_OAUTH_TOKEN. Without it, run_primitive_plan boots the
# container with no auth env, the entrypoint exits 1, and every exec_run
# returns "409 container is not running". Fail fast with a clear message.
if [[ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
    cat <<MSG >&2
error: CLAUDE_CODE_OAUTH_TOKEN is not set.

The agent container's entrypoint requires Claude Code authentication.
Without this env var, the container exits at startup and every agent
turn fails with a Docker 409 "container is not running" error.

Either export the token in your shell or add it to ${ENV_FILE}:
    CLAUDE_CODE_OAUTH_TOKEN=...
MSG
    exit 1
fi

# --- Defaults ----------------------------------------------------------------

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
UNIQUE_SUFFIX="$(printf '%04x' $((RANDOM % 65536)))"

: "${AGENT_BASE_IMAGE:=agent-worker:latest}"
: "${WORKSPACE_VOLUME:=italian-eval-${TIMESTAMP}-${UNIQUE_SUFFIX}}"
: "${ARTIFACTS_DIR:=${SCRIPT_DIR}/.artifacts/${TIMESTAMP}-${UNIQUE_SUFFIX}}"
: "${OUT_DIR:=${SCRIPT_DIR}/.runs}"

mkdir -p "${ARTIFACTS_DIR}"
mkdir -p "${OUT_DIR}"

# --- Forwarded args ----------------------------------------------------------
# Anything after `--` is appended to the pdm eval invocation as-is.
FORWARD_ARGS=()
if [[ "${1-}" == "--" ]]; then
    shift
    FORWARD_ARGS=("$@")
fi

# --- Run ---------------------------------------------------------------------

cat <<EOF
Running Italian-word classifier eval suite
  Suite:            ${SUITE}
  Base image:       ${AGENT_BASE_IMAGE}
  Workspace volume: ${WORKSPACE_VOLUME}
  Artifacts dir:    ${ARTIFACTS_DIR}
  Reports dir:      ${OUT_DIR}
EOF

if (( ${#FORWARD_ARGS[@]} )); then
    echo "  Extra args:       ${FORWARD_ARGS[*]}"
fi
echo

cd "${REPO_ROOT}"
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec pdm run python -m agent_foundry.evals.cli \
    "${SUITE}" \
    --artifacts-dir "${ARTIFACTS_DIR}" \
    --workspace-volume "${WORKSPACE_VOLUME}" \
    --base-image-tag "${AGENT_BASE_IMAGE}" \
    --out-dir "${OUT_DIR}" \
    "${FORWARD_ARGS[@]}"
