#!/bin/sh
# Mount an archipelago workspace volume and open a shell.
# Usage: ./browse-workspace.sh <volume-name>
#
# To list available volumes:
#   docker volume ls | grep archipelago

set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <volume-name>"
  echo ""
  echo "Available archipelago volumes:"
  docker volume ls --filter name=archipelago
  exit 1
fi

docker run --rm -it -v "$1":/workspace alpine sh
