"""Archipelago container environment variable builder.

Composes ACP-level lockdown env vars with Archipelago-specific
protocol and repository env vars into a single dict for container creation.
"""

from agent_foundry.acp.env import build_lockdown_env
from archipelago.docker_worker.models import WorkerInput


def build_container_env(worker_input: WorkerInput, ws_url: str) -> dict[str, str]:
    """Build the complete environment variable dict for an Archipelago container.

    Args:
        worker_input: Typed input containing lockdown config, repo info, and constraints.
        ws_url: WebSocket URL for the adapter to connect back to the orchestrator.

    Returns:
        Dict of env var name → value for passing to ContainerManager.create_container().
    """
    repo_env: dict[str, str] = {"REPO_REF": worker_input.repo_ref}
    if worker_input.repo_url and not worker_input.workspace_volume:
        repo_env["REPO_URL"] = worker_input.repo_url

    lockdown_env = build_lockdown_env(
        hidden_dirs=worker_input.acp_hidden_dirs or None,
        readonly_dirs=worker_input.acp_readonly_dirs or None,
        role_instructions_path=worker_input.role_instructions_path,
    )

    return {
        "ARCHIPELAGO_WS_URL": ws_url,
        "ARCHIPELAGO_TURN_TIMEOUT": str(worker_input.constraints.turn_timeout_seconds),
        "ARCHIPELAGO_SKIP_PERMISSIONS": ("1" if worker_input.constraints.skip_permissions else "0"),
        **repo_env,
        **lockdown_env,
    }
