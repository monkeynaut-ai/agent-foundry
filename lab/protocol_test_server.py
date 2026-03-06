#!/usr/bin/env python3
"""Interactive WebSocket server for testing the protocol adapter manually.

Usage with headless adapter (recommended — clean structured output):
    Terminal 1: python protocol_test_server.py
    Terminal 2: python headless_adapter.py --protocol ws://localhost:8765 "your prompt here"

Usage with PTY adapter (raw TUI output, needs noise filtering):
    Terminal 1: python protocol_test_server.py
    Terminal 2: python adapter.py --protocol ws://localhost:8765 claude

Type at the 'send>' prompt to send InputMessages to the adapter.
Incoming protocol messages are printed as they arrive. TUI chrome
(box drawing, spinner frames, status bars) is filtered out for PTY adapter output.
"""

import json
import re
import sys
import threading

from websockets.sync.server import serve

# Lines that are only box-drawing, whitespace, or decorative characters
_BOX_CHARS = set("─│╭╮╰╯┌┐└┘├┤┬┴┼━┃╋╔╗╚╝║═╠╣╦╩╬▐▌▀▄█▓░╴╶╵╷")
_SPINNER_CHARS = set("✦✶✻✽✳✴✵✷✸✹✺·•*✢✣✤✥✧✩✪✫✬✭✮✯✰✱✲")

def _is_tui_noise(text: str) -> bool:
    """Return True if the line is TUI chrome we should filter out."""
    stripped = text.strip()
    if not stripped:
        return True
    # Pure box-drawing / decorative lines
    if all(ch in _BOX_CHARS | {" "} for ch in stripped):
        return True
    # Lines starting with a spinner/decorative character — spinner status lines
    if stripped[0] in _SPINNER_CHARS:
        return True
    # Short fragments (≤5 chars) — progressive rendering debris
    if len(stripped) <= 5:
        return True
    # Status bar / chrome
    noise_patterns = [
        r"^esc to interrupt",
        r"^\? for shortcuts",
        r"^ctrl\+g to edit",
        r"^❯ ",  # input echo
        r"^❯$",
    ]
    for pat in noise_patterns:
        if re.match(pat, stripped):
            return True
    return False


def handler(ws):
    def reader():
        for raw in ws:
            msg = json.loads(raw)
            msg_type = msg["type"]

            if msg_type == "status":
                status = msg["status"]
                detail = msg.get("detail", "")
                exit_code = msg.get("exit_code")
                parts = [f"[{status}]"]
                if exit_code is not None:
                    parts.append(f"exit_code={exit_code}")
                if detail:
                    parts.append(detail)
                print(f"\033[90m── {' '.join(parts)}\033[0m")

            elif msg_type == "interrupt":
                itype = msg["interrupt_type"]
                payload = msg["payload"]
                print(f"\033[1;33m⚡ [{itype}] {json.dumps(payload)}\033[0m")

            elif msg_type == "output":
                text = msg["text"]
                if not _is_tui_noise(text):
                    print(f"  {text}")

            sys.stdout.flush()

    threading.Thread(target=reader, daemon=True).start()

    while True:
        try:
            text = input("\033[36msend>\033[0m ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        # Local commands (not sent to adapter)
        if text == "/done":
            msg = {"type": "control", "session_id": "test", "command": "complete"}
            ws.send(json.dumps(msg))
            print("\033[90m── sent control:complete\033[0m")
            continue
        if text == "/quit":
            msg = {"type": "control", "session_id": "test", "command": "terminate"}
            ws.send(json.dumps(msg))
            print("\033[90m── sent control:terminate\033[0m")
            break

        if text:
            msg = {"type": "input", "session_id": "test", "text": text + "\n"}
            ws.send(json.dumps(msg))
        else:
            # Empty enter = send just \n (trust confirmation / submit)
            msg = {"type": "input", "session_id": "test", "text": "\n"}
            ws.send(json.dumps(msg))


if __name__ == "__main__":
    print("Listening on ws://localhost:8765")
    print()
    print("Headless (recommended):")
    print("  python headless_adapter.py --protocol ws://localhost:8765 'your prompt'")
    print()
    print("PTY (raw TUI):")
    print("  python adapter.py --protocol ws://localhost:8765 claude")
    print()
    print("Commands:  /done = signal task complete  |  /quit = terminate adapter")
    print()
    with serve(handler, "localhost", 8765) as server:
        server.serve_forever()
