#!/bin/bash
# Build the Archipelago worker Docker image.
# Must be run from the project root or the docker/ directory.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

docker build -t archipelago-cc-worker:latest -f "$SCRIPT_DIR/Dockerfile" "$PROJECT_ROOT"
