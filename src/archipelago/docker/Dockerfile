# Archipelago Claude Code Worker
#
# Layers Archipelago-specific customizations on the ACP base image.
# Pyright and LSP plugin are now in the base image.
#
# Build (from project root):
#   pdm run docker-base
#   pdm run docker-archipelago

FROM acp-cc-worker:latest

# Archipelago-specific settings (merges with base settings.json)
COPY --chown=claude:claude src/archipelago/docker/settings.local.json /home/claude/.claude/settings.local.json

# Archipelago worker instructions and skills
COPY --chown=claude:claude src/archipelago/docker/CLAUDE.md /home/claude/.claude/CLAUDE.md
COPY --chown=claude:claude src/archipelago/docker/skills/lessons-learned/SKILL.md /home/claude/.claude/skills/lessons-learned/SKILL.md

# Archipelago marker configuration for the ACP adapter
COPY --chown=claude:claude src/archipelago/docker/marker-config.json /home/claude/marker-config.json

# Product init script — version check, product-specific setup
COPY --chown=claude:claude src/archipelago/docker/product-init.sh /home/claude/product-init.sh
RUN chmod +x /home/claude/product-init.sh

WORKDIR /workspace
