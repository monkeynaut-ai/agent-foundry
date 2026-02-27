#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

info()  { printf "${GREEN}[✓]${NC} %s\n" "$1"; }
warn()  { printf "${YELLOW}[!]${NC} %s\n" "$1"; }
fail()  { printf "${RED}[✗]${NC} %s\n" "$1"; exit 1; }

cd "$(dirname "$0")"

# --- 1. Check prerequisites ---

command -v git >/dev/null 2>&1 || fail "git is not installed"
info "git found"

command -v pdm >/dev/null 2>&1 || fail "pdm is not installed — install with: pip install pdm"
info "pdm found ($(pdm --version))"

REQUIRED_PYTHON="3.13"
PYTHON_PATH=""

# Find a Python 3.13 interpreter: prefer pdm-managed, fall back to system
if PYTHON_PATH=$(pdm python list 2>/dev/null | grep "cpython@${REQUIRED_PYTHON}" | head -1 | sed 's/.*(\(.*\))/\1/'); then
    if [[ -z "$PYTHON_PATH" ]]; then
        PYTHON_PATH=""
    fi
fi
if [[ -z "$PYTHON_PATH" ]] && command -v "python${REQUIRED_PYTHON}" >/dev/null 2>&1; then
    PYTHON_PATH=$(command -v "python${REQUIRED_PYTHON}")
fi
if [[ -z "$PYTHON_PATH" ]]; then
    fail "Python $REQUIRED_PYTHON not found — install it with: pdm python install $REQUIRED_PYTHON"
fi
info "Python $REQUIRED_PYTHON found ($PYTHON_PATH)"

# --- 2. Install dependencies ---

echo ""
echo "Selecting Python interpreter..."
pdm use "$PYTHON_PATH"

echo "Installing dependencies..."
pdm install
info "Dependencies installed"

# --- 3. Set up .env ---

echo ""
if [[ ! -f .env ]]; then
    cp .env.example .env
    warn ".env created from .env.example — edit it to add your API keys"
else
    info ".env already exists"
fi

# --- 4. Run tests ---

echo ""
echo "Running tests..."
if pdm run pytest; then
    info "All tests passed"
else
    warn "Some tests failed — check output above"
fi

# --- 5. Summary ---

echo ""
echo "========================================="
info "Bootstrap complete!"
echo ""
echo "  Run tests:   pdm run pytest"
echo "  Run demo:    pdm run demo"
echo "========================================="
