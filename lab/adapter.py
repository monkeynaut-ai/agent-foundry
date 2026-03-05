#!/usr/bin/env python3
"""PTY adapter: launches a subprocess with a PTY, bridges terminal I/O."""

import os
import socket
import sys
import termios
import threading
import tty

import pexpect
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve


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
    args = parser.parse_args()

    if args.ws:
        host, _, port_str = args.ws.rpartition(":")
        sys.exit(run_ws_adapter(args.command, host or "localhost", int(port_str)))
    elif args.socket:
        sys.exit(run_socket_adapter(args.command, args.socket))
    else:
        sys.exit(run_adapter(args.command))
