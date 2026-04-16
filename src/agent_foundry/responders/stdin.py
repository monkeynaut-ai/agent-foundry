"""Stdin-backed responder.

``StdinResponder`` serializes concurrent ``respond`` calls with an
``asyncio.Lock`` so the human at the terminal always answers one
question at a time. Each prompt is written to stdout (not via
``input``'s prompt arg) and discloses:

* kind (``clarification`` vs ``permission``),
* a queue-depth marker when the lock is contended,
* the agent identity and turn coordinates,
* the question or action summary.

The blocking ``input()`` call is offloaded to a worker thread via
``asyncio.get_running_loop().run_in_executor`` so the event loop keeps
serving other coroutines while the human types.
"""

from __future__ import annotations

import asyncio
import sys

from agent_foundry.responders.models import (
    ClarificationRequest,
    PermissionRequest,
    ResponderContext,
    ResponderKind,
    ResponderRequest,
    ResponderResponse,
)


class StdinResponder:
    """Prompt the human on stdout and read a single line from stdin."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # Number of coroutines currently waiting to acquire the lock.
        # Incremented before ``acquire`` and decremented once acquired.
        self._waiting = 0

    async def respond(
        self, request: ResponderRequest, context: ResponderContext
    ) -> ResponderResponse:
        # Capture queue depth as seen by this caller before it blocks
        # on the lock. A non-zero value means at least one other
        # caller is ahead of us (either holding the lock or queued).
        queue_depth = self._waiting
        if self._lock.locked():
            queue_depth = max(queue_depth, 1)

        self._waiting += 1
        acquired = False
        try:
            await self._lock.acquire()
            acquired = True
            self._waiting -= 1
            prompt = _format_prompt(request, queue_depth=queue_depth)
            sys.stdout.write(prompt)
            sys.stdout.flush()
            answer = await _read_line_async()
            return ResponderResponse(answer=answer.rstrip("\n"))
        finally:
            if acquired:
                self._lock.release()
            else:
                # Cancellation while waiting on the lock: undo the
                # pending-waiter bump so subsequent callers see an
                # accurate queue depth.
                self._waiting -= 1


def _format_prompt(request: ResponderRequest, *, queue_depth: int) -> str:
    queue_suffix = f" \u00b7 queue {queue_depth}" if queue_depth > 0 else ""
    identity = f"{request.agent_name}#{request.invocation} (turn {request.turn})"

    if request.kind is ResponderKind.CLARIFICATION:
        assert isinstance(request, ClarificationRequest)
        header = f"[clarification{queue_suffix}] {identity} \u2014 question:"
        body = f"  {request.question}"
    else:
        assert isinstance(request, PermissionRequest)
        header = f"[permission{queue_suffix}] {identity} \u2014 action:"
        body = f"  {request.action_summary}"

    return f"{header}\n{body}\n> "


async def _read_line_async() -> str:
    """Read a single line, preferring ``input()`` and falling back to
    ``sys.stdin`` when ``input()`` raises (e.g., EOF or piped stdin
    under certain test harnesses)."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, input)
    except EOFError:
        # Fall back to reading directly from sys.stdin — supports
        # piped input and test stubs that patch ``sys.stdin`` only.
        return await loop.run_in_executor(None, sys.stdin.readline)
