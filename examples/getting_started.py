"""Minimal Agent Foundry process from the Getting Started guide.

Run from the repository root:

    pdm run python examples/getting_started.py
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from pydantic import BaseModel

from agent_foundry import FunctionAction, Process, RunCompleted, Sequence, run_process
from agent_foundry.responders import (
    Responder,
    ResponderContext,
    ResponderRequest,
    ResponderResponse,
    static_provider,
)


class DraftInput(BaseModel):
    topic: str


class DraftState(BaseModel):
    topic: str
    outline: str


class DraftOutput(BaseModel):
    topic: str
    outline: str
    title: str


class NoopResponder(Responder):
    """Responder placeholder for a function-only process."""

    async def respond(
        self, request: ResponderRequest, context: ResponderContext
    ) -> ResponderResponse:
        raise RuntimeError("function-only example does not use responder requests")


def outline(state: DraftInput) -> DraftState:
    return DraftState(topic=state.topic, outline=f"Notes about {state.topic}")


def title(state: DraftState) -> DraftOutput:
    return DraftOutput(
        topic=state.topic,
        outline=state.outline,
        title=f"Understanding {state.topic}",
    )


process = Process(
    root=Sequence[DraftInput, DraftOutput](
        steps=[
            FunctionAction[DraftInput, DraftState](function=outline),
            FunctionAction[DraftState, DraftOutput](function=title),
        ]
    )
)


async def main() -> None:
    process.validate()

    with tempfile.TemporaryDirectory() as tmp:
        outcome = await run_process(
            process,
            initial_state=DraftInput(topic="typed agent workflows"),
            artifacts_dir=Path(tmp),
            workspace_volume="getting-started-workspace",
            base_image_tag="agent-foundry-base:latest",
            responder_provider=static_provider(NoopResponder()),
        )

    if not isinstance(outcome, RunCompleted):
        raise RuntimeError(outcome)

    print(outcome.output)


if __name__ == "__main__":
    asyncio.run(main())
