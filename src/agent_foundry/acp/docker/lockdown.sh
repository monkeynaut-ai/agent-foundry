#!/bin/sh
# ACP filesystem lockdown — runs as root before user drop.
# Reusable across any agent container image built on Agent Foundry.
#
# Env vars:
#   ACP_HIDDEN_DIRS   — comma-separated paths to make completely inaccessible (chmod 000)
#   ACP_READONLY_DIRS — comma-separated paths to make read-only (chmod -R a-w)

if [ -n "$ACP_HIDDEN_DIRS" ]; then
  IFS=',' ; for dir in $ACP_HIDDEN_DIRS; do
    [ -d "$dir" ] && chmod 000 "$dir"
  done; unset IFS
fi
if [ -n "$ACP_READONLY_DIRS" ]; then
  IFS=',' ; for dir in $ACP_READONLY_DIRS; do
    [ -d "$dir" ] && chmod -R a-w "$dir"
  done; unset IFS
fi
