"""Docker worker handler: orchestrates container lifecycle behind the standard handler interface."""

import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Literal

import docker

from archipelago.docker_worker.container import ContainerManager
from archipelago.docker_worker.interrupts import InterruptDetector, InterruptHandler
from archipelago.docker_worker.models import (
    CommitEvidence,
    PatchInfo,
    UpdateAvailable,
    WorkerInput,
    WorkerResult,
)
from archipelago.docker_worker.progress import parse_progress
from archipelago.docker_worker.recovery import persist_workspace_state
from archipelago.docker_worker.session import SessionManager

logger = logging.getLogger(__name__)


def docker_worker_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Orchestrate a full Docker worker lifecycle.

    Extracts worker_input from state, creates/starts a container,
    launches a CC session, streams output, handles interrupts,
    collects progress, and returns worker_result.
    """
    worker_input_data = state.get("worker_input", {})
    worker_input = WorkerInput(**worker_input_data)

    # Initialize subsystems
    try:
        client = docker.from_env()
    except Exception as e:
        logger.error("Docker unavailable: %s", e)
        result = WorkerResult(
            result_summary=f"Docker unavailable: {e}",
            workspace_ref="",
            patches=[],
            evidence=[],
            status="failed",
        )
        return {**state, "worker_result": result.model_dump()}

    container_mgr = ContainerManager(client)
    session_mgr = SessionManager(container_mgr)
    detector = InterruptDetector()
    interrupt_handler = InterruptHandler(
        session_mgr,
        detector,
        auto_approve_low_risk=worker_input.constraints.network_policy != "none",
    )

    # Collect output lines and detect interrupts/notifications
    output_lines: list[str] = []
    interrupt_request = None
    update_available: dict[str, str] | None = None

    def _output_callback(line: str, _container_id: str, _timestamp: float) -> None:
        nonlocal interrupt_request, update_available
        output_lines.append(line)
        detected = detector.scan_line(line)
        if isinstance(detected, UpdateAvailable):
            update_available = {"installed": detected.installed, "latest": detected.latest}
        elif detected is not None:
            interrupt_request = detected

    session_mgr.register_output_callback(_output_callback)

    container_handle = None
    try:
        # Create and start container
        container_handle = container_mgr.create_container(
            workspace_volume=f"archipelago-{int(time.time())}",
            constraints=worker_input.constraints,
        )
        container_mgr.start(container_handle, repo_ref=worker_input.repo_ref)

        # Launch CC session
        session = session_mgr.launch_session(
            container_handle, "/home/claude/entrypoint.sh"
        )

        # Wait for session to exit or interrupt
        deadline = time.time() + worker_input.constraints.timeout_seconds
        while session.status == "running" and time.time() < deadline:
            if interrupt_request is not None:
                updated = interrupt_handler.handle_interrupt(
                    interrupt_request,
                    session,
                    state,
                )
                if "breakpoint_payload" in updated:
                    return {**state, **updated, "worker_result": None}
                interrupt_request = None
            time.sleep(0.1)

        # Determine status
        status: Literal["completed", "failed", "timed_out"]
        if time.time() >= deadline:
            status = "timed_out"
        elif session.exit_code == 0:
            status = "completed"
        else:
            status = "failed"

        # Parse progress from workspace
        events = parse_progress(Path(container_handle.workspace_path))

        patches = []
        evidence = []
        for event in events:
            if event.type == "pr_completed":
                patches.append(PatchInfo(
                    pr_id=event.pr_id,
                    branch_name=event.commit_id,
                    files_changed=event.files_changed,
                    diff_summary=event.notes,
                ))
            if event.type == "commit_green":
                evidence.append(CommitEvidence(
                    commit_id=event.commit_id,
                    pr_id=event.pr_id,
                    test_commands_run=[r.command for r in event.tests_run],
                    test_output=event.notes,
                    tests_passed=sum(1 for r in event.tests_run if r.exit_code == 0),
                    tests_failed=sum(1 for r in event.tests_run if r.exit_code != 0),
                    all_green=all(r.exit_code == 0 for r in event.tests_run),
                ))

        result = WorkerResult(
            result_summary=f"Worker {status} with {len(output_lines)} output lines",
            workspace_ref=container_handle.workspace_path,
            patches=patches,
            evidence=evidence,
            status=status,
        )
        result_state = {**state, "worker_result": result.model_dump()}
        if update_available:  # pyright: ignore[reportUnreachable] — reachable via nonlocal mutation from _output_callback thread
            result_state["update_available"] = update_available
        return result_state

    except Exception as e:
        logger.error("Docker worker error: %s", e)
        if container_handle:
            try:
                recovery_dir = Path(tempfile.mkdtemp(prefix="archipelago-recovery-"))
                persist_workspace_state(
                    Path(container_handle.workspace_path),
                    recovery_dir,
                )
            except Exception:
                pass

        result = WorkerResult(
            result_summary=f"Worker failed: {e}",
            workspace_ref="",
            patches=[],
            evidence=[],
            status="failed",
        )
        return {**state, "worker_result": result.model_dump()}
    finally:
        if container_handle:
            import contextlib

            with contextlib.suppress(Exception):
                container_mgr.destroy(container_handle)


class DockerWorkerHandler:
    """Wrapper class matching the ImplementationPointer pattern (cls(spec).__call__)."""

    def __init__(self, spec: Any = None):
        self.spec = spec

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return docker_worker_handler(state)


DOCKER_WORKER_HANDLERS: dict[str, Any] = {
    "coding_implement_feature_from_spec": docker_worker_handler,
}
