#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <container-name-or-id> [command...]"
    echo ""
    echo "Determines the image and /workspace volume from an exited container,"
    echo "then runs a new container with that volume mounted and port 5000 exposed."
    echo ""
    echo "Examples:"
    echo "  $0 youthful_einstein python app.py --host 0.0.0.0"
    echo "  $0 cc9fa11f5286 bash"
    exit 1
fi

container="$1"
shift

# Resolve image
image=$(docker inspect "$container" --format '{{.Config.Image}}')
if [ -z "$image" ]; then
    echo "Error: could not determine image for container '$container'" >&2
    exit 1
fi

# Find the volume mounted at /workspace
volume=$(docker inspect "$container" --format '{{range .Mounts}}{{if eq .Destination "/workspace"}}{{.Name}}{{end}}{{end}}')
if [ -z "$volume" ]; then
    echo "Error: no volume mounted at /workspace in container '$container'" >&2
    exit 1
fi

# Default command: auto-detect framework and run the app
if [ $# -eq 0 ]; then
    set -- sh -c '
        if .venv/bin/python -c "import flask" 2>/dev/null; then
            echo "Detected Flask"
            FLASK_APP=app.py .venv/bin/flask run --host 0.0.0.0 --port 5000
        elif .venv/bin/python -c "import uvicorn" 2>/dev/null; then
            echo "Detected FastAPI/uvicorn"
            .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 5000
        else
            echo "No Flask or uvicorn found in .venv" >&2
            exit 1
        fi
    '
fi

echo "Image:  $image"
echo "Volume: $volume"
echo "Command: $*"
echo ""

docker run --rm -it \
    -p 5000:5000 \
    -v "$volume":/workspace \
    -w /workspace \
    --entrypoint "" \
    "$image" \
    "$@"
