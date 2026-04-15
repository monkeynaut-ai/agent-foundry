"""Test fakes for the orchestration layer (F0 shape).

Phase B.4 and F.3 extend FakeContainerManager and add FakeContainer
features (exec_run scripting, put_archive round-trip, etc.). F0
only needs create/start/write_file/destroy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeContainerHandle:
    container_id: str
    workspace_path: str = "/workspace"
    status: str = "created"
    files: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)


class FakeContainerManager:
    """F0 shape: create_container / start / write_file_to_container /
    destroy. Phase B.4 and F.3 extend.
    """

    def __init__(self) -> None:
        self.handles: list[FakeContainerHandle] = []
        self._next_id = 0

    def create_container(
        self,
        image: str | None = None,
        workspace_volume: str = "",
        constraints: Any = None,
        extra_env: dict[str, str] | None = None,
    ) -> FakeContainerHandle:
        self._next_id += 1
        h = FakeContainerHandle(
            container_id=f"fake-{self._next_id}",
            env=dict(extra_env or {}),
        )
        self.handles.append(h)
        return h

    def start(self, handle: FakeContainerHandle) -> None:
        handle.status = "running"

    def write_file_to_container(self, handle: FakeContainerHandle, path: str, content: str) -> None:
        handle.files[path] = content

    def destroy(self, handle: FakeContainerHandle) -> None:
        handle.status = "destroyed"

    def stop(self, handle: FakeContainerHandle, timeout: int = 10) -> None:
        handle.status = "stopped"


class FakeClaudeCodeAdapter:
    """Scripted adapter returning canned envelope payloads per turn.

    F0 only uses run_turn once per invocation and only supports
    success envelopes. F.3's inner-loop tests extend this fake.
    """

    def __init__(self, *, canned_structured_output: dict[str, Any]) -> None:
        self._canned = canned_structured_output
        self.calls: list[dict[str, Any]] = []

    async def run_turn(
        self,
        *,
        prompt: str,
        json_schema: dict[str, Any],
        resume_session_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"prompt": prompt, "schema": json_schema, "resume": resume_session_id})
        return self._canned
