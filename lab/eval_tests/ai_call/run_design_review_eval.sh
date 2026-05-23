#!/usr/bin/env bash
#
# Run the design-review AICall eval suite.
#
# Defaults:
#   * Report output: ./lab/eval_tests/.runs/
#
# Override via env vars:
#   OUT_DIR=/some/other/path
#
# Extra args after `--` are forwarded to the eval CLI:
#   ./run_design_review_eval.sh -- --max-concurrency 4 --invocations 3
#
# Unlike the agent-target eval, this path doesn't use containers: the
# AICall runs in-process via invoke_ai_call. No CLAUDE_CODE_OAUTH_TOKEN,
# no workspace volume, no artifacts dir. The AnthropicProvider does
# need ANTHROPIC_API_KEY in the environment.
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
REPO_ROOT="$( cd "${SCRIPT_DIR}/../.." && pwd )"
SUITE="${SCRIPT_DIR}/design_review_suite.py"

if [[ ! -f "${SUITE}" ]]; then
    echo "error: suite file not found: ${SUITE}" >&2
    exit 1
fi

# Load the repo-root .env if present so users can keep secrets there
# (e.g. ANTHROPIC_API_KEY) instead of exporting them every shell.
ENV_FILE="${REPO_ROOT}/.env"
if [[ -f "${ENV_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    cat <<MSG >&2
error: ANTHROPIC_API_KEY is not set.

The AnthropicProvider needs an API key to issue inference calls.
Either export it in your shell or add it to ${ENV_FILE}:
    ANTHROPIC_API_KEY=...
MSG
    exit 1
fi

: "${OUT_DIR:=${SCRIPT_DIR}/.runs}"
mkdir -p "${OUT_DIR}"

FORWARD_ARGS=()
if [[ "${1-}" == "--" ]]; then
    shift
    FORWARD_ARGS=("$@")
fi

cat <<EOF
Running design-review AICall eval suite
  Suite:       ${SUITE}
  Reports dir: ${OUT_DIR}
EOF

if (( ${#FORWARD_ARGS[@]} )); then
    echo "  Extra args:  ${FORWARD_ARGS[*]}"
fi
echo

cd "${REPO_ROOT}"
# Add ${REPO_ROOT} so the suite can import sibling modules under
# lab.eval_tests.* (namespace packages, no __init__.py required).
export PYTHONPATH="${REPO_ROOT}/src:${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
exec pdm run python -m agent_foundry.evals.cli \
    "${SUITE}" \
    --out-dir "${OUT_DIR}" \
    "${FORWARD_ARGS[@]}"
