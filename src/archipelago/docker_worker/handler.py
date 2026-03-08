"""Docker worker handler: orchestrates container lifecycle behind the standard handler interface."""

import contextlib
import logging
import queue
import socket
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import docker
from websockets.sync.server import ServerConnection, serve

from archipelago.docker_worker.container import ContainerManager
from archipelago.docker_worker.models import (
    CommitEvidence,
    PatchInfo,
    WorkerConstraints,
    WorkerInput,
    WorkerResult,
)
from archipelago.docker_worker.progress import parse_progress
from archipelago.docker_worker.protocol import (
    ControlMessage,
    InputMessage,
    InterruptMessage,
    OutputMessage,
    ProtocolError,
    StatusMessage,
    parse_protocol_message,
)
from archipelago.docker_worker.recovery import persist_workspace_state

logger = logging.getLogger(__name__)


def _get_free_port() -> int:
    """Find an available port."""
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _generate_session_id() -> str:
    """Generate a unique session ID."""
    return str(uuid.uuid4())


class _HandlerWSServer:
    """Ephemeral WebSocket server for a single adapter connection."""

    def __init__(self) -> None:
        self.message_queue: queue.Queue[str | None] = queue.Queue()
        self.connected = threading.Event()
        self._ws: ServerConnection | None = None
        self._server = None
        self._server_thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self, port: int) -> None:
        def _handler(ws: ServerConnection) -> None:
            with self._lock:
                self._ws = ws
            self.connected.set()
            try:
                while True:
                    try:
                        raw = ws.recv(timeout=0.5)
                        self.message_queue.put(raw if isinstance(raw, str) else raw.decode())
                    except TimeoutError:
                        continue
            except Exception:
                pass
            finally:
                self.message_queue.put(None)  # sentinel

        self._server = serve(_handler, "localhost", port)
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()

    def send(self, message: str) -> None:
        with self._lock:
            ws = self._ws
        if ws:
            with contextlib.suppress(Exception):
                ws.send(message)

    def shutdown(self) -> None:
        if self._server:
            with contextlib.suppress(Exception):
                self._server.shutdown()


def _build_prompt(worker_input: WorkerInput) -> str:
    """Format the worker input into a prompt string for Claude Code."""
    spec = worker_input.feature_spec
    parts = ["Implement the following feature:"]
    if title := spec.get("title"):
        parts.append(f"Title: {title}")
    if description := spec.get("description"):
        parts.append(f"Description: {description}")
    if requirements := spec.get("requirements"):
        parts.append("Requirements:")
        for req in requirements:
            parts.append(f"  - {req}")
    if worker_input.test_commands:
        parts.append(f"Test commands: {', '.join(worker_input.test_commands)}")
    if worker_input.gates:
        parts.append(f"Gates: {', '.join(worker_input.gates)}")
    return "\n".join(parts)


def _send_input(ws_server: _HandlerWSServer, session_id: str, text: str) -> None:
    """Send an InputMessage through the WebSocket server."""
    msg = InputMessage(type="input", session_id=session_id, text=text)
    ws_server.send(msg.model_dump_json())


def _send_control(
    ws_server: _HandlerWSServer,
    session_id: str,
    command: Literal["resize", "terminate", "kill"],
    args: dict[str, Any] | None = None,
) -> None:
    """Send a ControlMessage through the WebSocket server."""
    msg = ControlMessage(
        type="control",
        session_id=session_id,
        command=command,
        args=args or {},
    )
    ws_server.send(msg.model_dump_json())


def docker_worker_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Orchestrate a full Docker worker lifecycle.

    Extracts worker_input from state, creates/starts a container,
    starts a WS server for the adapter to connect to, processes
    structured protocol messages, and returns worker_result.
    """
    worker_input_data = state.get("worker_input")
    if worker_input_data:
        worker_input = WorkerInput(**worker_input_data)
    else:
        worker_input = WorkerInput(
            repo_ref=state.get("repo_ref", "main"),
            feature_spec=state.get("feature_spec", {}),
            constraints=WorkerConstraints(**state.get("worker_constraints", {})),
            test_commands=state.get("test_commands", ["pdm run pytest"]),
            gates=state.get("gates", []),
        )

    auto_approve_low_risk = worker_input.constraints.network_policy != "none"

    # Initialize Docker
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

    # Start WS server on ephemeral port
    ws_server = _HandlerWSServer()
    port = _get_free_port()
    session_id = _generate_session_id()
    ws_server.start(port)

    container_handle = None
    try:
        # Create and start container with WS URL
        ws_url = f"ws://host.docker.internal:{port}/{session_id}"
        repo_env: dict[str, str] = {"REPO_REF": worker_input.repo_ref}
        if worker_input.repo_url:
            repo_env["REPO_URL"] = worker_input.repo_url
        container_handle = container_mgr.create_container(
            workspace_volume=f"archipelago-{int(time.time())}",
            constraints=worker_input.constraints,
            extra_env={
                "ARCHIPELAGO_WS_URL": ws_url,
                "ARCHIPELAGO_TURN_TIMEOUT": str(worker_input.constraints.turn_timeout_seconds),
                "ARCHIPELAGO_SKIP_PERMISSIONS": (
                    "1" if worker_input.constraints.skip_permissions else "0"
                ),
                **repo_env,
            },
        )
        container_mgr.start(container_handle)

        # Wait for adapter to connect
        if not ws_server.connected.wait(timeout=60):
            raise TimeoutError("Adapter did not connect within 60 seconds")

        # Collect output and state
        output_lines: list[str] = []
        mutable: dict[str, Any] = {"update_available": None}
        session_exit_code: int | None = None

        # Send the feature spec prompt immediately — headless adapter waits for first input
        _send_input(ws_server, session_id, _build_prompt(worker_input))

        # Message processing loop
        deadline = time.time() + worker_input.constraints.timeout_seconds

        while time.time() < deadline:
            try:
                raw = ws_server.message_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # Connection dropped sentinel
            if raw is None:
                result = WorkerResult(
                    result_summary="Adapter connection dropped",
                    workspace_ref=container_handle.workspace_path if container_handle else "",
                    patches=[],
                    evidence=[],
                    status="failed",
                )
                return {**state, "worker_result": result.model_dump()}

            try:
                msg = parse_protocol_message(raw)
            except ProtocolError:
                logger.warning("Ignoring malformed protocol message")
                continue

            if isinstance(msg, OutputMessage):
                output_lines.append(msg.text)
                print(f"[cc] {msg.text}", flush=True)

            elif isinstance(msg, InterruptMessage):
                if msg.interrupt_type == "update_available":
                    mutable["update_available"] = msg.payload
                elif msg.interrupt_type == "clarification":
                    payload = msg.payload
                    blocking = payload.get("blocking", True)
                    if blocking:
                        return {
                            **state,
                            "breakpoint_payload": {
                                "type": "clarification",
                                "question": payload.get("question", ""),
                                "options": payload.get("options", []),
                                "default": payload.get("default"),
                            },
                            "worker_result": None,
                        }
                elif msg.interrupt_type == "permission":
                    payload = msg.payload
                    risk_level = payload.get("risk_level", "medium")
                    if risk_level == "low" and auto_approve_low_risk:
                        _send_input(ws_server, session_id, "yes\n")
                    else:
                        return {
                            **state,
                            "breakpoint_payload": {
                                "type": "permission",
                                "action": payload.get("action", ""),
                                "risk_level": risk_level,
                                "why_needed": payload.get("why_needed", ""),
                            },
                            "worker_result": None,
                        }

            elif isinstance(msg, StatusMessage):
                if msg.status == "exited":
                    session_exit_code = msg.exit_code
                    break
                elif msg.status == "completed":
                    # Task done — gate check not yet implemented (backlog item)
                    session_exit_code = 0
                    break

        # Determine status
        status: Literal["completed", "failed", "timed_out"]
        if time.time() >= deadline and session_exit_code is None:
            _send_control(ws_server, session_id, "terminate")
            status = "timed_out"
        elif session_exit_code == 0:
            status = "completed"
        else:
            status = "failed"

        # Copy progress file from container, then parse locally
        progress_dir = Path(tempfile.mkdtemp(prefix="archipelago-progress-"))
        container_mgr.copy_from_container(
            container_handle,
            f"{container_handle.workspace_path}/progress.jsonl",
            progress_dir / "progress.jsonl",
        )
        events = parse_progress(progress_dir)

        patches = []
        evidence = []
        for event in events:
            if event.type == "pr_completed":
                patches.append(
                    PatchInfo(
                        pr_id=event.pr_id,
                        branch_name=event.commit_id,
                        files_changed=event.files_changed,
                        diff_summary=event.notes,
                    )
                )
            if event.type == "commit_green":
                evidence.append(
                    CommitEvidence(
                        commit_id=event.commit_id,
                        pr_id=event.pr_id,
                        test_commands_run=[r.command for r in event.tests_run],
                        test_output=event.notes,
                        tests_passed=sum(1 for r in event.tests_run if r.exit_code == 0),
                        tests_failed=sum(1 for r in event.tests_run if r.exit_code != 0),
                        all_green=all(r.exit_code == 0 for r in event.tests_run),
                    )
                )

        result = WorkerResult(
            result_summary=f"Worker {status} with {len(output_lines)} output lines",
            workspace_ref=container_handle.workspace_path,
            patches=patches,
            evidence=evidence,
            status=status,
        )
        result_state = {**state, "worker_result": result.model_dump()}
        if mutable["update_available"]:
            result_state["update_available"] = mutable["update_available"]
        return result_state

    except Exception as e:
        logger.error("Docker worker error: %s", e)
        if container_handle:
            try:
                recovery_dir = Path(tempfile.mkdtemp(prefix="archipelago-recovery-"))
                persist_workspace_state(
                    workspace_path=None,
                    output_path=recovery_dir,
                    container_mgr=container_mgr,
                    container_handle=container_handle,
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
        ws_server.shutdown()
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
