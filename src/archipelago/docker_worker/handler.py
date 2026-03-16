"""Docker worker handler: orchestrates container lifecycle behind the standard handler interface."""

import contextlib
import logging
import queue
import shutil
import socket
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import docker
from websockets.sync.server import ServerConnection, serve

from archipelago.docker_worker.container import create_archipelago_container_manager
from archipelago.docker_worker.env import build_container_env
from archipelago.docker_worker.models import (
    WorkerConstraints,
    WorkerInput,
    WorkerResult,
)
from archipelago.docker_worker.progress import parse_progress, transform_progress_events
from archipelago.docker_worker.protocol import (
    AgentEventMessage,
    ControlMessage,
    InputMessage,
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
                logger.debug("WebSocket handler loop ended", exc_info=True)
            finally:
                self.message_queue.put(None)  # sentinel

        self._server = serve(_handler, "0.0.0.0", port)
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()

    def send(self, message: str) -> bool:
        with self._lock:
            ws = self._ws
        if not ws:
            return False
        try:
            ws.send(message)
            return True
        except Exception:
            logger.debug("WebSocket send failed", exc_info=True)
            return False

    def shutdown(self) -> None:
        if self._server:
            with contextlib.suppress(Exception):
                self._server.shutdown()


def _build_prompt(worker_input: WorkerInput) -> str:
    """Format the worker input into a prompt string for Claude Code."""
    spec = worker_input.feature_spec

    parts = (
        list(worker_input.prompt_preamble)
        if worker_input.prompt_preamble
        else ["Implement the following feature:"]
    )

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


def _send_input(ws_server: _HandlerWSServer, session_id: str, text: str) -> bool:
    """Send an InputMessage through the WebSocket server. Returns True on success."""
    msg = InputMessage(type="input", session_id=session_id, text=text)
    return ws_server.send(msg.model_dump_json())


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


@dataclass
class MessageLoopResult:
    """Outcome of the message processing loop."""

    output_lines: list[str] = field(default_factory=list)
    session_exit_code: int | None = None
    update_available: dict[str, Any] | None = None
    early_return: dict[str, Any] | None = None


def _process_messages(
    ws_server: _HandlerWSServer,
    session_id: str,
    deadline: float,
    auto_approve_low_risk: bool,
    state: dict[str, Any],
    workspace_path: str,
) -> MessageLoopResult:
    """Process protocol messages from the adapter until completion, breakpoint, or timeout.

    Returns a MessageLoopResult. If early_return is not None, the caller should
    return it directly as the handler result (contains breakpoint_payload).
    """
    result = MessageLoopResult()

    while time.time() < deadline:
        try:
            raw = ws_server.message_queue.get(timeout=0.1)
        except queue.Empty:
            continue

        # Connection dropped sentinel
        if raw is None:
            failed = WorkerResult(
                result_summary="Adapter connection dropped",
                workspace_ref=workspace_path,
                patches=[],
                evidence=[],
                status="failed",
            )
            result.early_return = {**state, "worker_result": failed.model_dump()}
            return result

        try:
            msg = parse_protocol_message(raw)
        except ProtocolError:
            logger.warning("Ignoring malformed protocol message")
            continue

        if isinstance(msg, OutputMessage):
            result.output_lines.append(msg.text)
            logger.info("[cc] %s", msg.text)

        elif isinstance(msg, AgentEventMessage):
            if msg.event_type == "update_available":
                result.update_available = msg.payload
            elif msg.event_type == "clarification_requested":
                payload = msg.payload
                blocking = payload.get("blocking", True)
                if blocking:
                    result.early_return = {
                        **state,
                        "breakpoint_payload": {
                            "type": "clarification",
                            "question": payload.get("question", ""),
                            "options": payload.get("options", []),
                            "default": payload.get("default"),
                            "blocking": True,
                        },
                        "worker_result": None,
                    }
                    return result
            elif msg.event_type == "permission_requested":
                payload = msg.payload
                risk_level = payload.get("risk_level", "medium")
                if risk_level == "low" and auto_approve_low_risk:
                    if not _send_input(ws_server, session_id, "yes\n"):
                        failed = WorkerResult(
                            result_summary="Send failed: could not auto-approve permission",
                            workspace_ref=workspace_path,
                            patches=[],
                            evidence=[],
                            status="failed",
                        )
                        result.early_return = {**state, "worker_result": failed.model_dump()}
                        return result
                else:
                    result.early_return = {
                        **state,
                        "breakpoint_payload": {
                            "type": "permission",
                            "action": payload.get("action", ""),
                            "risk_level": risk_level,
                            "why_needed": payload.get("why_needed", ""),
                        },
                        "worker_result": None,
                    }
                    return result

        elif isinstance(msg, StatusMessage):
            if msg.status == "exited":
                result.session_exit_code = msg.exit_code
                break
            elif msg.status == "completed":
                # Task done — gate check not yet implemented (backlog item)
                result.session_exit_code = 0
                break

    return result


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

    # Merge node config from system JSON (injected into state by the compiler)
    if role := state.get("worker_mode"):
        worker_input.worker_mode = role
    if acp_hidden_dirs := state.get("acp_hidden_dirs"):
        worker_input.acp_hidden_dirs = acp_hidden_dirs
    if acp_readonly_dirs := state.get("acp_readonly_dirs"):
        worker_input.acp_readonly_dirs = acp_readonly_dirs
    if role_instructions_path := state.get("role_instructions_path"):
        worker_input.role_instructions_path = role_instructions_path
    if workspace_volume := state.get("workspace_volume"):
        worker_input.workspace_volume = workspace_volume
    if prompt_preamble := state.get("prompt_preamble"):
        worker_input.prompt_preamble = prompt_preamble

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

    container_mgr = create_archipelago_container_manager(client)

    # Start WS server on ephemeral port
    ws_server = _HandlerWSServer()
    port = _get_free_port()
    session_id = _generate_session_id()
    ws_server.start(port)

    container_handle = None
    temp_dirs: list[Path] = []
    try:
        # Create and start container with WS URL
        ws_url = f"ws://host.docker.internal:{port}/{session_id}"
        volume_name = worker_input.workspace_volume or f"archipelago-{int(time.time())}"

        container_handle = container_mgr.create_container(
            workspace_volume=volume_name,
            constraints=worker_input.constraints,
            extra_env=build_container_env(worker_input, ws_url),
        )
        container_mgr.start(container_handle)

        # Wait for adapter to connect (git clone + npm version check can be slow)
        conn_timeout = worker_input.constraints.connection_timeout_seconds
        if not ws_server.connected.wait(timeout=conn_timeout):
            raise TimeoutError(f"Adapter did not connect within {conn_timeout} seconds")

        # Send the feature spec prompt immediately — headless adapter waits for first input
        if not _send_input(ws_server, session_id, _build_prompt(worker_input)):
            result = WorkerResult(
                result_summary="Send failed: could not deliver initial prompt",
                workspace_ref=container_handle.workspace_path if container_handle else "",
                patches=[],
                evidence=[],
                status="failed",
            )
            return {**state, "worker_result": result.model_dump()}

        # Process protocol messages
        deadline = time.time() + worker_input.constraints.timeout_seconds
        loop_result = _process_messages(
            ws_server=ws_server,
            session_id=session_id,
            deadline=deadline,
            auto_approve_low_risk=auto_approve_low_risk,
            state=state,
            workspace_path=container_handle.workspace_path if container_handle else "",
        )

        if loop_result.early_return is not None:
            return loop_result.early_return

        output_lines = loop_result.output_lines
        session_exit_code = loop_result.session_exit_code

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
        temp_dirs.append(progress_dir)
        container_mgr.copy_from_container(
            container_handle,
            f"{container_handle.workspace_path}/progress.jsonl",
            progress_dir / "progress.jsonl",
        )
        events = parse_progress(progress_dir)
        patches, evidence = transform_progress_events(events)

        result = WorkerResult(
            result_summary=f"Worker {status} with {len(output_lines)} output lines",
            workspace_ref=container_handle.workspace_path,
            patches=patches,
            evidence=evidence,
            status=status,
        )
        result_state = {**state, "worker_result": result.model_dump()}
        result_state["workspace_volume"] = volume_name
        if loop_result.update_available:
            result_state["update_available"] = loop_result.update_available
        return result_state

    except Exception as e:
        logger.error("Docker worker error: %s", e)
        if container_handle:
            try:
                recovery_dir = Path(tempfile.mkdtemp(prefix="archipelago-recovery-"))
                temp_dirs.append(recovery_dir)
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
            with contextlib.suppress(Exception):
                container_mgr.destroy(container_handle)
        for d in temp_dirs:
            with contextlib.suppress(Exception):
                shutil.rmtree(d)


class DockerWorkerHandler:
    """Wrapper class matching the ImplementationPointer pattern (cls(spec).__call__)."""

    def __init__(self, spec: Any = None):
        self.spec = spec

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        return docker_worker_handler(state)
