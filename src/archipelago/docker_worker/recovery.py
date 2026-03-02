"""Crash recovery: persist workspace state and restore into fresh containers."""

import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from archipelago.docker_worker.container import ContainerHandle, ContainerManager
from archipelago.docker_worker.models import ProgressEvent, ResumePoint
from archipelago.docker_worker.progress import parse_progress
from archipelago.docker_worker.session import SessionHandle, SessionManager


class WorkspaceSnapshot(BaseModel):
    """Captured state of a workspace for recovery."""

    commit_sha: str
    working_tree_diff: str
    progress_events: list[ProgressEvent]
    transcript_path: str | None = None


def persist_workspace_state(
    workspace_path: Path,
    output_path: Path,
    git_runner: Any = None,
) -> WorkspaceSnapshot:
    """Capture workspace git state and progress for recovery.

    Args:
        workspace_path: Path to the workspace directory.
        output_path: Path to write the snapshot artifacts.
        git_runner: Optional callable for git commands (default: subprocess).
    """
    import subprocess

    output_path.mkdir(parents=True, exist_ok=True)

    # Capture git state
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

    # Parse progress events
    events = parse_progress(workspace_path)

    # Copy progress file if exists
    progress_src = workspace_path / "progress.jsonl"
    if progress_src.exists():
        shutil.copy2(progress_src, output_path / "progress.jsonl")

    # Copy transcript if exists
    transcript_path = None
    transcript_src = workspace_path / "transcript.log"
    if transcript_src.exists():
        shutil.copy2(transcript_src, output_path / "transcript.log")
        transcript_path = str(output_path / "transcript.log")

    return WorkspaceSnapshot(
        commit_sha=commit_sha,
        working_tree_diff=diff,
        progress_events=events,
        transcript_path=transcript_path,
    )


def recover_session(
    container_manager: ContainerManager,
    session_manager: SessionManager,
    workspace_volume: str,
    feature_spec: dict,
    last_checkpoint: ResumePoint | None = None,
    image: str | None = None,
    command: str = "claude-code --yes",
) -> tuple[ContainerHandle, SessionHandle]:
    """Restore a crashed session into a fresh container.

    Creates a new container with the same workspace volume, starts it,
    and launches a new CC session with resume context.
    """
    container = container_manager.create_container(
        image=image,
        workspace_volume=workspace_volume,
    )
    container_manager.start(container)

    # Build resume context for CC
    resume_cmd = command
    if last_checkpoint:
        resume_cmd = (
            f"{command} --resume-from '{last_checkpoint.pr_id}/{last_checkpoint.commit_id}'"
        )

    session = session_manager.launch_session(container, resume_cmd)
    return container, session
