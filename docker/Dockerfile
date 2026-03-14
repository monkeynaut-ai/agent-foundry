# Archipelago Claude Code Worker
#
# Layers Archipelago-specific customizations on the ACP base image.
#
# Build (from project root):
#   docker build -t acp-cc-worker:latest -f src/agent_foundry/acp/docker/Dockerfile.base .
#   docker build -t archipelago-cc-worker:latest -f docker/Dockerfile .

FROM acp-cc-worker:latest

# Install Pyright language server for LSP code intelligence.
# The first invocation downloads a bundled Node.js — do it at build time
# so the container starts with Pyright ready immediately.
RUN pip install --no-cache-dir pyright \
    && pyright --version

# Archipelago-specific settings (adds plugin config on top of ACP base)
COPY --chown=claude:claude docker/settings.json /home/claude/.claude/settings.json

# Archipelago worker instructions and skills
COPY --chown=claude:claude docker/CLAUDE.md /home/claude/.claude/CLAUDE.md
COPY --chown=claude:claude docker/skills/lessons-learned/SKILL.md /home/claude/.claude/skills/lessons-learned/SKILL.md

# Archipelago marker configuration for the ACP adapter
COPY --chown=claude:claude docker/marker-config.json /home/claude/marker-config.json

# Product init script — installs Pyright plugin at container start
COPY --chown=claude:claude docker/product-init.sh /home/claude/product-init.sh
RUN chmod +x /home/claude/product-init.sh

WORKDIR /workspace
