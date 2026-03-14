"""Container lifecycle manager for Archipelago Docker workers.

Re-exports ACP container infrastructure with Archipelago-specific defaults.
"""

from agent_foundry.acp.container import (  # noqa: F401
    ContainerConfig,
    ContainerHandle,
    ContainerManager,
    DEFAULT_ENV_ALLOWLIST as _ACP_ENV_ALLOWLIST,
)

# Archipelago extends the generic ACP allowlist with product-specific env vars
DEFAULT_ENV_ALLOWLIST = _ACP_ENV_ALLOWLIST | {
    "ARCHIPELAGO_WS_URL",
    "GITHUB_TOKEN",
    "GIT_USER_NAME",
    "GIT_USER_EMAIL",
}


def create_archipelago_container_manager(client, **kwargs) -> ContainerManager:
    """Factory that creates a ContainerManager with Archipelago defaults."""
    return ContainerManager(
        client,
        default_image=kwargs.get("default_image", "archipelago-cc-worker:latest"),
        env_allowlist=kwargs.get("env_allowlist", DEFAULT_ENV_ALLOWLIST),
    )
