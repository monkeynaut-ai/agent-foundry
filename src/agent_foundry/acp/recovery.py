"""Generic workspace state capture for containerized agents.

Captures git state (commit SHA, working tree diff) and optional transcript
from a workspace — either on the host filesystem or inside a container.
Product-specific progress interpretation is left to the product.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent_foundry.acp.container import ContainerHandle, ContainerManager


class WorkspaceSnapshot(BaseModel):
    """Captured git state of a workspace for recovery."""

    commit_sha: str
    working_tree_diff: str
    transcript_path: str | None = None


def capture_workspace_state(
    output_path: Path,
    workspace_path: Path | None = None,
    git_runner: Any = None,
    container_mgr: ContainerManager | None = None,
    container_handle: ContainerHandle | None = None,
) -> WorkspaceSnapshot:
    """Capture workspace git state for recovery.

    Supports two modes:
    - Host mode: workspace_path is a local directory
    - Container mode: container_mgr + container_handle for remote I/O

    Args:
        output_path: Directory to write snapshot artifacts.
        workspace_path: Path to workspace (host mode).
        git_runner: Optional callable for git commands (host mode).
        container_mgr: ContainerManager for container-based I/O.
        container_handle: ContainerHandle for container-based I/O.
    """
    output_path.mkdir(parents=True, exist_ok=True)

    if container_mgr is not None and container_handle is not None:
        return _capture_via_container(container_mgr, container_handle, output_path)

    assert workspace_path is not None, "workspace_path required when not using container API"

    if git_runner:
        commit_sha = git_runner("rev-parse", "HEAD", cwd=workspace_path)
        diff = git_runner("diff", cwd=workspace_path)
    else:
        try:
            commit_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=workspace_path,
                text=True,
            ).strip()
        except Exception:
            commit_sha = "unknown"

        try:
            diff = subprocess.check_output(
                ["git", "diff"],
                cwd=workspace_path,
                text=True,
            )
        except Exception:
            diff = ""

    transcript_path = None
    transcript_src = workspace_path / "transcript.log"
    if transcript_src.exists():
        shutil.copy2(transcript_src, output_path / "transcript.log")
        transcript_path = str(output_path / "transcript.log")

    return WorkspaceSnapshot(
        commit_sha=commit_sha,
        working_tree_diff=diff,
        transcript_path=transcript_path,
    )


def _capture_via_container(
    container_mgr: ContainerManager,
    container_handle: ContainerHandle,
    output_path: Path,
) -> WorkspaceSnapshot:
    """Capture workspace state from inside a running container."""
    ws = container_handle.workspace_path

    exit_code, output = container_handle._container.exec_run(f"git -C {ws} rev-parse HEAD")
    commit_sha = output.decode().strip() if exit_code == 0 else "unknown"

    exit_code, output = container_handle._container.exec_run(f"git -C {ws} diff")
    diff = output.decode() if exit_code == 0 else ""

    transcript_path = None
    container_mgr.copy_from_container(
        container_handle, f"{ws}/transcript.log", output_path / "transcript.log"
    )
    if (output_path / "transcript.log").exists():
        transcript_path = str(output_path / "transcript.log")

    return WorkspaceSnapshot(
        commit_sha=commit_sha,
        working_tree_diff=diff,
        transcript_path=transcript_path,
    )
