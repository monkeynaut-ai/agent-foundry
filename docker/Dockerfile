FROM python:3.13-slim

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl jq \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user matching container.py's user="1000:1000"
RUN groupadd -g 1000 claude \
    && useradd -m -u 1000 -g claude -s /bin/sh claude

USER claude
ENV HOME=/home/claude
WORKDIR /home/claude

# Install Claude Code native binary
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PATH="/home/claude/.local/bin:${PATH}"

# Verify installation
RUN claude --version

# Install Python dependencies for the headless adapter
RUN pip install --no-cache-dir websockets

# Copy configuration and entrypoint
# Build context must be the project root:
#   docker build -t archipelago-cc-worker:latest -f docker/Dockerfile .
COPY --chown=claude:claude docker/settings.json /home/claude/.claude/settings.json
COPY --chown=claude:claude docker/CLAUDE.md /home/claude/.claude/CLAUDE.md
COPY --chown=claude:claude docker/claude.json /home/claude/.claude.json
COPY --chown=claude:claude docker/skills/lessons-learned/SKILL.md /home/claude/.claude/skills/lessons-learned/SKILL.md
COPY --chown=claude:claude docker/entrypoint.sh /home/claude/entrypoint.sh
RUN chmod +x /home/claude/entrypoint.sh
COPY --chown=claude:claude src/archipelago/docker_worker/headless_adapter.py /home/claude/adapter.py

WORKDIR /workspace

ENTRYPOINT ["/home/claude/entrypoint.sh"]
