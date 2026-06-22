"""Container env composition for the container executor.

Lifted loosely from Archipelago's docker_worker/env.py composition
pattern: caller-supplied extras merge first, then required agent
env vars overwrite to guarantee they win.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_foundry.constructs.models import AgentAction


def build_container_env(
    construct: AgentAction,
    *,
    oauth_token: str,
    role_instructions_path: str,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Compose the env dict passed to ContainerManager.create_container.

    The required agent keys (CLAUDE_CODE_OAUTH_TOKEN, AGENT_HOST_DRIVEN,
    AGENT_ROLE_INSTRUCTIONS_PATH) always win over ``extra``; callers use
    ``extra`` for optional additions (REPO_URL, GIT_USER_NAME, etc.).

    AGENT_HOST_DRIVEN=1 tells the container entrypoint to idle (tail -f
    /dev/null) after setup instead of launching an in-container
    adapter — the orchestration stack drives claude via host-side
    ``docker exec``. See the foundation smoke test in
    tests/agent_foundry/integration/test_foundation_smoke.py for the
    end-to-end proof.
    """
    env: dict[str, str] = {}
    if extra:
        env.update(extra)
    env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
    env["AGENT_HOST_DRIVEN"] = "1"
    env["AGENT_ROLE_INSTRUCTIONS_PATH"] = role_instructions_path
    return env
