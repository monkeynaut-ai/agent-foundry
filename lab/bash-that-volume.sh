#!/bin/bash
# Start an interactive shell in a new container, reusing the image and
# workspace volume from an existing (possibly exited) container.
#
# Usage:
#   ./bash-that-volume.sh <container_name_or_id>
#   ./bash-that-volume.sh <volume_name>              (legacy mode)
#
# The script inspects the given container to find:
#   1. The Docker image it was created from
#   2. The volume mounted at /workspace
# Then runs a new interactive container with that image and volume.

set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <container_name_or_id>"
  echo ""
  echo "  Inspects the container to find its image and /workspace volume,"
  echo "  then starts a new interactive shell with the same image and volume."
  echo ""
  echo "  Also accepts a bare volume name for backward compatibility."
  exit 1
fi

TARGET="$1"

# Check if the argument is a container (name or ID)
if docker inspect --type container "$TARGET" >/dev/null 2>&1; then
  # Extract the image
  IMAGE=$(docker inspect "$TARGET" --format '{{.Config.Image}}')

  # Extract the volume or bind mount at /workspace
  # Prefer .Name (named volume); fall back to .Source (bind mount)
  VOLUME=$(docker inspect "$TARGET" --format '{{range .Mounts}}{{if eq .Destination "/workspace"}}{{if .Name}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}')

  if [ -z "$VOLUME" ]; then
    echo "ERROR: Container '$TARGET' has no mount at /workspace"
    echo ""
    echo "Mounts found:"
    docker inspect "$TARGET" --format '{{range .Mounts}}  {{.Destination}} → {{.Name}}{{.Source}}{{"\n"}}{{end}}'
    exit 1
  fi

  echo "Container: $TARGET"
  echo "Image:     $IMAGE"
  echo "Volume:    $VOLUME"
  echo ""

  docker run -it --rm \
    --entrypoint /bin/bash \
    -v "$VOLUME":/workspace \
    "$IMAGE"

# Check if the argument is a volume name (legacy mode)
elif docker volume inspect "$TARGET" >/dev/null 2>&1; then
  echo "Volume: $TARGET (legacy mode — using default image)"
  echo ""

  docker run -it --rm \
    --entrypoint /bin/bash \
    -v "$TARGET":/workspace \
    archipelago-cc-worker:latest

else
  echo "ERROR: '$TARGET' is not a container or volume"
  echo ""
  echo "Containers with /workspace mounts:"
  docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | head -20
  exit 1
fi
