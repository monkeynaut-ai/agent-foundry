#!/bin/sh
# Archipelago entrypoint — delegates to ACP base entrypoint.
# This file is no longer COPY'd into the container. The base image's
# entrypoint.sh handles everything via the product-init.sh hook.
#
# Kept for documentation and local development only.
echo "This entrypoint is superseded by the ACP base image entrypoint."
echo "See src/agent_foundry/acp/docker/entrypoint.sh"
exit 1
