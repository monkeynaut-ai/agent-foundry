"""Docker worker handler: orchestrates container lifecycle behind the standard handler interface."""

import logging
import time
from typing import Any

import docker

from archipelago.docker_worker.container import ContainerManager
from archipelago.docker_worker.interrupts import InterruptDetector, InterruptHandler
from archipelago.docker_worker.models import (
    CommitEvidence,
    PatchInfo,
    WorkerConstraints,
    WorkerInput,
    WorkerResult,
)
from archipelago.docker_worker.progress import get_resume_point, parse_progress
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
        session_mgr, detector,
        auto_approve_low_risk=worker_input.constraints.network_policy != "none",
    )

    # Collect output lines and detect interrupts
    output_lines: list[str] = []
    interrupt_request = None

    def _output_callback(line: str, container_id: str, timestamp: float) -> None:
        nonlocal interrupt_request
        output_lines.append(line)
        detected = detector.scan_line(line)
        if detected is not None:
            interrupt_request = detected

    session_mgr.register_output_callback(_output_callback)

    container_handle = None
    try:
        # Create and start container
        container_handle = container_mgr.create_container(
            repo_ref=worker_input.repo_ref,
            workspace_volume=f"archipelago-{int(time.time())}",
            constraints=worker_input.constraints,
        )
        container_mgr.start(container_handle, repo_ref=worker_input.repo_ref)

        # Launch CC session
        session = session_mgr.launch_session(
            container_handle, "claude-code --yes"
        )

        # Wait for session to exit or interrupt
        deadline = time.time() + worker_input.constraints.timeout_seconds
        while session.status == "running" and time.time() < deadline:
            if interrupt_request is not None:
                updated = interrupt_handler.handle_interrupt(
                    interrupt_request, session, state,
                )
                if "breakpoint_payload" in updated:
                    return {**state, **updated, "worker_result": None}
                interrupt_request = None
            time.sleep(0.1)

        # Determine status
        if time.time() >= deadline:
            status = "timed_out"
        elif session.exit_code == 0:
            status = "completed"
        else:
            status = "failed"

        # Parse progress
        from pathlib import Path
        workspace_path = Path(container_handle.workspace_path)
        # In real usage, this would read from the container's mounted volume
        # For now, build result from available state

        result = WorkerResult(
            result_summary=f"Worker {status} with {len(output_lines)} output lines",
            workspace_ref=container_handle.workspace_path,
            patches=[],
            evidence=[],
            status=status,
        )
        return {**state, "worker_result": result.model_dump()}

    except Exception as e:
        logger.error("Docker worker error: %s", e)
        if container_handle:
            try:
                from pathlib import Path
                persist_workspace_state(
                    Path(container_handle.workspace_path),
                    Path("/tmp/archipelago-recovery"),
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
            try:
                container_mgr.destroy(container_handle)
            except Exception:
                pass


DOCKER_WORKER_HANDLERS: dict[str, Any] = {
    "coding_implement_feature_from_spec": docker_worker_handler,
}
