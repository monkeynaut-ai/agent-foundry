#!/usr/bin/env python3
"""PTY adapter: launches a subprocess with a PTY, bridges terminal I/O."""

import json
import logging
import os
import re
import socket
import sys
import termios
import threading
import time
import tty

import pexpect
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as ws_connect
from websockets.sync.server import serve

logger = logging.getLogger(__name__)

# Duplicate interrupt patterns here to keep lab/ self-contained (no dependency on src/)
_INTERRUPT_PATTERN = re.compile(r"^ARCHIPELAGO_NEED_(CLARIFICATION|PERMISSION)\s+(\{.*\})$")
_UPDATE_PATTERN = re.compile(r"^ARCHIPELAGO_UPDATE_AVAILABLE\s+(\{.*\})$")


def run_adapter(command: str = "claude") -> int:
    """Launch command in a PTY, bridge stdin/stdout."""
    child = pexpect.spawn(command, encoding="utf-8", timeout=None)
    child.setwinsize(24, 80)

    def _read_output():
        while child.isalive():
            try:
                chunk = child.read_nonblocking(size=4096, timeout=0.1)
                if chunk:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
            except pexpect.TIMEOUT:
                continue
            except pexpect.EOF:
                break

    reader = threading.Thread(target=_read_output, daemon=True)
    reader.start()

    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setraw(sys.stdin.fileno())
        while child.isalive():
            char = os.read(sys.stdin.fileno(), 1)
            if not char:
                break
            child.send(char.decode("utf-8", errors="replace"))
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        if child.isalive():
            child.terminate()
        child.wait()

    return child.exitstatus or 0


def run_socket_adapter(command: str = "cat", socket_path: str = "/tmp/adapter.sock") -> int:
    """Launch command in a PTY, bridge I/O over a Unix domain socket."""
    if os.path.exists(socket_path):
        os.unlink(socket_path)

    child = pexpect.spawn(command, encoding=None, timeout=None)
    child.setwinsize(24, 80)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    server.listen(1)

    conn, _ = server.accept()

    def _pty_to_socket():
        while child.isalive():
            try:
                chunk = child.read_nonblocking(size=4096, timeout=0.1)
                if chunk:
                    conn.sendall(chunk)
            except pexpect.TIMEOUT:
                continue
            except (pexpect.EOF, OSError):
                break

    def _socket_to_pty():
        conn.settimeout(0.5)
        while child.isalive():
            try:
                data = conn.recv(4096)
                if not data:
                    break
                child.send(data)
            except socket.timeout:
                continue
            except OSError:
                break

    t1 = threading.Thread(target=_pty_to_socket, daemon=True)
    t2 = threading.Thread(target=_socket_to_pty, daemon=True)
    t1.start()
    t2.start()

    t2.join()
    if child.isalive():
        child.terminate()
    child.wait()

    conn.close()
    server.close()
    if os.path.exists(socket_path):
        os.unlink(socket_path)

    return child.exitstatus or 0


def run_ws_adapter(command: str = "cat", host: str = "localhost", port: int = 8765) -> int:
    """Launch command in a PTY, bridge I/O over a WebSocket."""
    child = pexpect.spawn(command, encoding=None, timeout=None)
    child.setwinsize(24, 80)

    done = threading.Event()

    def handler(ws):
        def _pty_to_ws():
            while child.isalive():
                try:
                    chunk = child.read_nonblocking(size=4096, timeout=0.1)
                    if chunk:
                        ws.send(chunk)
                except pexpect.TIMEOUT:
                    continue
                except (pexpect.EOF, OSError, ConnectionClosed):
                    break

        t = threading.Thread(target=_pty_to_ws, daemon=True)
        t.start()

        try:
            while child.isalive():
                try:
                    message = ws.recv(timeout=0.5)
                    child.send(message if isinstance(message, bytes) else message.encode())
                except TimeoutError:
                    continue
        except ConnectionClosed:
            pass
        finally:
            done.set()

    server = serve(handler, host, port)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    done.wait()
    if child.isalive():
        child.terminate()
    child.wait()
    server.shutdown()

    return child.exitstatus or 0


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\].*?\x07|\x1b\(B", "", text)


def _connect_with_backoff(ws_url: str, timeout: float = 30.0):
    """Connect to a WebSocket with exponential backoff. Returns the connection."""
    intervals = [0.5, 1.0, 2.0, 4.0]
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        try:
            return ws_connect(ws_url)
        except (ConnectionRefusedError, OSError) as e:
            if time.monotonic() >= deadline:
                raise ConnectionError(
                    f"Could not connect to {ws_url} within {timeout}s"
                ) from e
            delay = intervals[min(attempt, len(intervals) - 1)]
            remaining = deadline - time.monotonic()
            time.sleep(min(delay, max(0, remaining)))
            attempt += 1


def run_protocol_adapter(
    command: str, ws_url: str, session_id: str, connect_timeout: float = 30.0,
) -> int:
    """Launch command in a PTY, bridge I/O over WebSocket using structured protocol messages.

    The adapter connects outward to ws_url as a client. It emits typed JSON messages
    (OutputMessage, InterruptMessage, StatusMessage) and receives InputMessage/ControlMessage.
    """
    child = pexpect.spawn(command, encoding=None, timeout=None)
    child.setwinsize(24, 80)

    try:
        ws = _connect_with_backoff(ws_url, timeout=connect_timeout)
    except ConnectionError:
        if child.isalive():
            child.terminate()
        child.wait()
        return 1

    ts = time.time

    def _send_msg(msg: dict) -> None:
        try:
            ws.send(json.dumps(msg))
        except (ConnectionClosed, OSError):
            pass

    # Send started status
    _send_msg({"type": "status", "session_id": session_id, "status": "started", "timestamp": ts()})

    child_done = threading.Event()
    first_output_sent = threading.Event()

    def _child_alive():
        try:
            return child.isalive()
        except (pexpect.ExceptionPexpect, OSError):
            return False

    def _reader_thread():
        """Read PTY output, buffer on \\n, strip ANSI, detect interrupts, emit messages."""
        buf = b""
        while _child_alive():
            try:
                chunk = child.read_nonblocking(size=4096, timeout=0.1)
                if not chunk:
                    continue
                buf += chunk
                while b"\n" in buf:
                    line_bytes, buf = buf.split(b"\n", 1)
                    line = line_bytes.decode("utf-8", errors="replace")
                    clean = _strip_ansi(line).strip()
                    if not clean:
                        continue

                    if not first_output_sent.is_set():
                        _send_msg({"type": "status", "session_id": session_id,
                                   "status": "running", "timestamp": ts()})
                        first_output_sent.set()

                    # Check for interrupt markers
                    interrupt_match = _INTERRUPT_PATTERN.match(clean)
                    update_match = _UPDATE_PATTERN.match(clean)

                    if interrupt_match:
                        kind = interrupt_match.group(1)
                        payload_str = interrupt_match.group(2)
                        try:
                            payload = json.loads(payload_str)
                            itype = "clarification" if kind == "CLARIFICATION" else "permission"
                            _send_msg({
                                "type": "interrupt", "session_id": session_id,
                                "interrupt_type": itype, "payload": payload,
                                "raw_line": clean, "timestamp": ts(),
                            })
                        except json.JSONDecodeError:
                            logger.warning("Malformed interrupt JSON: %s", clean)
                            _send_msg({
                                "type": "output", "session_id": session_id,
                                "text": clean, "stream": "stdout", "timestamp": ts(),
                            })
                    elif update_match:
                        payload_str = update_match.group(1)
                        try:
                            payload = json.loads(payload_str)
                            _send_msg({
                                "type": "interrupt", "session_id": session_id,
                                "interrupt_type": "update_available", "payload": payload,
                                "raw_line": clean, "timestamp": ts(),
                            })
                        except json.JSONDecodeError:
                            logger.warning("Malformed update JSON: %s", clean)
                            _send_msg({
                                "type": "output", "session_id": session_id,
                                "text": clean, "stream": "stdout", "timestamp": ts(),
                            })
                    else:
                        _send_msg({
                            "type": "output", "session_id": session_id,
                            "text": clean, "stream": "stdout", "timestamp": ts(),
                        })
            except pexpect.TIMEOUT:
                continue
            except pexpect.EOF:
                break

        # Flush remaining buffer
        if buf:
            remaining = _strip_ansi(buf.decode("utf-8", errors="replace")).strip()
            if remaining:
                _send_msg({
                    "type": "output", "session_id": session_id,
                    "text": remaining, "stream": "stdout", "timestamp": ts(),
                })

        child_done.set()

    reader = threading.Thread(target=_reader_thread, daemon=True)
    reader.start()

    # Main thread: receive WS messages and dispatch to PTY
    try:
        while _child_alive():
            try:
                raw = ws.recv(timeout=0.5)
            except TimeoutError:
                continue
            except ConnectionClosed:
                break

            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                logger.warning("Ignoring malformed WS message")
                continue

            msg_type = msg.get("type")
            if msg_type == "input":
                text = msg.get("text", "")
                child.send(text.replace("\n", "\r").encode())
            elif msg_type == "control":
                cmd = msg.get("command")
                if cmd == "resize":
                    args = msg.get("args", {})
                    child.setwinsize(args.get("rows", 24), args.get("cols", 80))
                elif cmd == "terminate":
                    if _child_alive():
                        child.terminate()
                elif cmd == "kill":
                    if _child_alive():
                        child.kill(9)
    except ConnectionClosed:
        pass

    # Wait for child to exit
    if _child_alive():
        child.terminate()
    try:
        child.wait()
    except (pexpect.ExceptionPexpect, OSError):
        pass

    # Wait for reader to flush
    child_done.wait(timeout=2)

    exit_code = child.exitstatus if child.exitstatus is not None else child.signalstatus or 1
    _send_msg({
        "type": "status", "session_id": session_id, "status": "exited",
        "exit_code": exit_code, "timestamp": ts(),
    })

    try:
        ws.close()
    except Exception:
        pass

    return exit_code


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PTY adapter")
    parser.add_argument("command", nargs="?", default="claude", help="command to run")
    parser.add_argument("--socket", metavar="PATH", help="listen on a Unix domain socket")
    parser.add_argument(
        "--ws",
        nargs="?",
        const="localhost:8765",
        metavar="HOST:PORT",
        help="listen on a WebSocket (default: localhost:8765)",
    )
    parser.add_argument(
        "--protocol",
        metavar="WS_URL",
        help="run in protocol mode, connecting to WS_URL as a client",
    )
    args = parser.parse_args()

    if args.protocol:
        sys.exit(run_protocol_adapter(args.command, args.protocol, session_id="default"))
    elif args.ws:
        host, _, port_str = args.ws.rpartition(":")
        sys.exit(run_ws_adapter(args.command, host or "localhost", int(port_str)))
    elif args.socket:
        sys.exit(run_socket_adapter(args.command, args.socket))
    else:
        sys.exit(run_adapter(args.command))
