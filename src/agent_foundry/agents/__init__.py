"""Platform infrastructure for containerized AI agents."""

# UID and GID of the non-root ``claude`` user in the agent-worker base
# image. Hosts that prepare files or directories on the workspace volume
# before the agent container starts (e.g. archipelago's
# ``prepare_documents_dir``) must chown them to this UID so the
# in-container ``claude`` user can write.
#
# IMPORTANT: this constant must match
# ``src/agent_foundry/agents/docker/Dockerfile.base`` lines 23-25:
#     RUN groupadd -g 1000 claude \
#         && useradd -m -u 1000 -g claude -s /bin/bash claude
# If the Dockerfile bumps the UID, bump it here in the same change.
AGENT_USER_UID = 1000
AGENT_USER_GID = 1000

__all__ = ["AGENT_USER_GID", "AGENT_USER_UID"]
