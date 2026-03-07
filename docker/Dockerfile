FROM python:3.13-slim

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl jq \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user matching container.py's user="1000:1000"
RUN groupadd -g 1000 claude \
    && useradd -m -u 1000 -g claude -s /bin/sh claude

USER claude
WORKDIR /home/claude

# Install Claude Code native binary
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PATH="/home/claude/.local/bin:${PATH}"

# Verify installation
RUN claude --version

# Copy configuration and entrypoint
COPY --chown=claude:claude settings.json /home/claude/.claude/settings.json
COPY --chown=claude:claude CLAUDE.md /home/claude/.claude/CLAUDE.md
COPY --chown=claude:claude claude.json /home/claude/.claude.json
COPY --chown=claude:claude entrypoint.sh /home/claude/entrypoint.sh
RUN chmod +x /home/claude/entrypoint.sh
COPY --chown=claude:claude adapter.py /home/claude/adapter.py

WORKDIR /workspace

ENTRYPOINT ["/home/claude/entrypoint.sh"]
