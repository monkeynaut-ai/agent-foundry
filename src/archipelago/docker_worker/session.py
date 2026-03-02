"""PTY session management and output streaming."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from archipelago.docker_worker.container import ContainerHandle
from archipelago.docker_worker.errors import SessionError


@dataclass
class SessionHandle:
    """Handle to an active PTY session inside a container."""

    exec_id: str
    container_id: str
    status: Literal["running", "paused", "exited"] = "running"
    exit_code: int | None = None
    started_at: float = field(default_factory=time.time)
    _socket: Any = field(default=None, repr=False)
    _stream: Any = field(default=None, repr=False)


class SessionManager:
    """Manages PTY sessions inside Docker containers."""

    def __init__(self, container_manager: Any = None):
        self._container_manager = container_manager
        self._callbacks: list[Callable[[str, str, float], None]] = []
        self._paused = threading.Event()
        self._paused.set()  # Start unpaused
        self._stream_thread: threading.Thread | None = None

    def register_output_callback(self, callback: Callable[[str, str, float], None]) -> None:
        """Register a callback receiving (line, container_id, timestamp)."""
        self._callbacks.append(callback)

    def launch_session(self, container_handle: ContainerHandle, command: str) -> SessionHandle:
        """Launch a persistent PTY session via docker exec."""
        try:
            container = container_handle._container
            exec_result = container.client.api.exec_create(
                container_handle.container_id,
                command,
                tty=True,
                stdin=True,
                stdout=True,
                stderr=True,
            )
            stream = container.client.api.exec_start(
                exec_result["Id"], stream=True, socket=True, tty=True
            )
        except Exception as e:
            raise SessionError(str(e), container_id=container_handle.container_id) from e

        handle = SessionHandle(
            exec_id=exec_result["Id"],
            container_id=container_handle.container_id,
            _socket=stream,
            _stream=stream,
        )

        self._stream_thread = threading.Thread(
            target=self._stream_output,
            args=(handle,),
            daemon=True,
        )
        self._stream_thread.start()

        return handle

    def send_input(self, session_handle: SessionHandle, text: str) -> None:
        """Write text to the PTY's stdin."""
        if session_handle._socket is not None:
            try:
                session_handle._socket._sock.sendall(text.encode())
            except Exception as e:
                raise SessionError(str(e), container_id=session_handle.container_id) from e

    def pause(self, session_handle: SessionHandle) -> None:
        """Pause output consumption. Container and PTY remain alive."""
        self._paused.clear()
        session_handle.status = "paused"

    def resume(self, session_handle: SessionHandle) -> None:
        """Resume output consumption."""
        self._paused.set()
        session_handle.status = "running"

    def _stream_output(self, session_handle: SessionHandle) -> None:
        """Background thread that reads from the exec stream and invokes callbacks."""
        buffer = ""
        try:
            for chunk in session_handle._stream:
                if isinstance(chunk, bytes):
                    chunk = chunk.decode("utf-8", errors="replace")
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    self._paused.wait()  # Block if paused
                    ts = time.monotonic()
                    for cb in self._callbacks:
                        cb(line, session_handle.container_id, ts)
        except Exception:
            pass
        finally:
            session_handle.status = "exited"
            # Try to get exit code
            try:
                inspect = session_handle._socket.client.api.exec_inspect(session_handle.exec_id)
                session_handle.exit_code = inspect.get("ExitCode")
            except Exception:
                pass
