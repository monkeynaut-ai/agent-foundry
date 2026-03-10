#!/bin/bash
# Start an interactive shell in a new archipelago-cc-worker container,
# mounting an existing workspace volume.
#
# Usage: ./shell.sh <volume_name>

if [ -z "$1" ]; then
  echo "Usage: $0 <volume_name>"
  exit 1
fi

docker run -it --rm \
  --entrypoint /bin/sh \
  -v "$1":/workspace \
  archipelago-cc-worker:latest
