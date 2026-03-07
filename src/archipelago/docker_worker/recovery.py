"""Crash recovery: persist workspace state and restore into fresh containers."""

import json
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
    workspace_path: Path | None,
    output_path: Path,
    git_runner: Any = None,
    container_mgr: ContainerManager | None = None,
    container_handle: ContainerHandle | None = None,
) -> WorkspaceSnapshot:
    """Capture workspace git state and progress for recovery.

    Args:
        workspace_path: Path to the workspace directory (host mode).
        output_path: Path to write the snapshot artifacts.
        git_runner: Optional callable for git commands (host mode).
        container_mgr: Optional ContainerManager for container-based I/O.
        container_handle: Optional ContainerHandle for container-based I/O.
    """
    import subprocess

    output_path.mkdir(parents=True, exist_ok=True)

    if container_mgr is not None and container_handle is not None:
        return _persist_via_container(container_mgr, container_handle, output_path)

    # Host-based path (original behavior)
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

    events = parse_progress(workspace_path)

    progress_src = workspace_path / "progress.jsonl"
    if progress_src.exists():
        shutil.copy2(progress_src, output_path / "progress.jsonl")

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


def _persist_via_container(
    container_mgr: ContainerManager,
    container_handle: ContainerHandle,
    output_path: Path,
) -> WorkspaceSnapshot:
    """Capture workspace state from inside a running container."""
    ws = container_handle.workspace_path

    # Git state via exec_run
    exit_code, output = container_handle._container.exec_run(f"git -C {ws} rev-parse HEAD")
    commit_sha = output.decode().strip() if exit_code == 0 else "unknown"

    exit_code, output = container_handle._container.exec_run(f"git -C {ws} diff")
    diff = output.decode() if exit_code == 0 else ""

    # Progress events via container API
    progress_content = container_mgr.read_file_from_container(
        container_handle, f"{ws}/progress.jsonl"
    )
    events: list[ProgressEvent] = []
    if progress_content:
        # Write to output_path so parse_progress can read it
        progress_dest = output_path / "progress.jsonl"
        progress_dest.write_text(progress_content)
        events = parse_progress(output_path)

    # Copy transcript if it exists
    transcript_path = None
    container_mgr.copy_from_container(
        container_handle, f"{ws}/transcript.log", output_path / "transcript.log"
    )
    if (output_path / "transcript.log").exists():
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
    command: str = "/home/claude/entrypoint.sh",
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

    # Write feature spec inside the container so CC has access to it
    if feature_spec:
        container_manager.write_file_to_container(
            container,
            f"{container.workspace_path}/feature_spec.json",
            json.dumps(feature_spec, indent=2),
        )

    # Build resume context for CC
    resume_cmd = command
    if last_checkpoint:
        resume_cmd = (
            f"{command} --resume-from '{last_checkpoint.pr_id}/{last_checkpoint.commit_id}'"
        )

    session = session_manager.launch_session(container, resume_cmd)
    return container, session
