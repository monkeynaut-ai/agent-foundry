"""Task H.1 end-to-end integration test.

Drives the full Plan 2 stack against the real ``acp-cc-worker:latest``
base image and real Claude Code via ``CLAUDE_CODE_OAUTH_TOKEN`` from
``.env``. The plan under test is a ``Sequence[StateA, StateC]`` of

    [AgentAction[StateA, StateB], FunctionAction[StateB, StateC]]

where the agent's output model carries one ``Annotated[str,
AgentFilePath()]`` field and one plain string field. The
``FunctionAction`` records a domain event via
``run_ctx.lifecycle_writer.append_run_event``.

Assertions cover:

* Final state matches the expected shape.
* ``<artifacts_dir>/<run-id>/lifecycle.jsonl`` contains the expected
  event sequence (``RUN_STARTED`` … ``RUN_ENDED``, incl. the domain
  event and the ``FUNCTION_ACTION_*`` bracket).
* ``<artifacts_dir>/<run-id>/<agent_name>/turns/0/`` contains
  ``prompt.txt``, ``envelope.json``, ``output.json``, and a
  ``collected_files/`` populated with the snapshotted file.
* ``<artifacts_dir>/<run-id>/inspect-workspace.sh`` is executable.
* ``<artifacts_dir>/<run-id>/summary.txt`` is rendered.
* No orphan containers after the run.

Fails (not skips) when ``CLAUDE_CODE_OAUTH_TOKEN`` is missing — if the
token is unavailable, the contract is broken; the test should shout.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Annotated, Any

import pytest
from dotenv import load_dotenv
from pydantic import BaseModel

from agent_foundry.compiler.primitive_compiler import run_primitive_plan
from agent_foundry.models.markers import AgentFilePath
from agent_foundry.orchestration.container_executor import run_agent_in_container
from agent_foundry.orchestration.lifecycle_events import LifecycleEvent
from agent_foundry.primitives.models import (
    AgentAction,
    ContainerReusePolicy,
    FunctionAction,
    Sequence,
)
from agent_foundry.primitives.plan import PrimitivePlan
from agent_foundry.responders.models import ResponderResponse
from agent_foundry.responders.protocol import static_provider

# Load .env from the agent-foundry repo root so CLAUDE_CODE_OAUTH_TOKEN
# is available when running via ``pdm test-integration``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env")


# --- State models -----------------------------------------------------------


class StateA(BaseModel):
    topic: str


class StateB(BaseModel):
    """Output of the AgentAction.

    ``note_path`` is declared as an ``AgentFilePath`` — the executor
    verifies this file exists inside the container after the agent
    turn and snapshots it into ``collected_files/``. ``headline`` is a
    plain string so the model covers both the marked and unmarked
    field cases the plan calls out in H.1.
    """

    headline: str
    note_path: Annotated[str, AgentFilePath()]


class StateC(BaseModel):
    headline: str
    verified: bool


# --- Responder that fails loudly if called ---------------------------------


class _UnusedResponder:
    """Happy-path responder: we do not expect it to be called.

    If the agent emits clarification/permission outcomes despite the
    instruction text, the test should fail with a clear message rather
    than hanging on stdin.
    """

    async def respond(self, request: Any, context: Any) -> ResponderResponse:
        raise AssertionError(
            f"responder unexpectedly invoked with {request!r} (context={context!r})"
        )


# --- The test ----------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_plan2_end_to_end_real_claude_code(tmp_path: Path) -> None:
    # Fail loudly — not skip — when the OAuth token is missing.
    oauth_token = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
    assert oauth_token  # used implicitly by ``run_primitive_plan`` via os.environ

    # Skip only on docker unavailability.
    try:
        import docker

        client = docker.from_env()
        client.ping()
    except Exception as e:
        pytest.skip(f"docker daemon unavailable: {e}")

    base_image = os.environ.get("ACP_BASE_IMAGE", "acp-cc-worker:latest")
    workspace_volume = f"plan2-e2e-{uuid.uuid4().hex[:8]}"

    # --- Build the plan ----------------------------------------------------

    # The agent should report the path of the CLAUDE.md file the
    # entrypoint has already materialised — a known-existing path lets
    # us exercise AgentFilePath verification + snapshotting without
    # asking the agent to run the Write tool. Asking claude to call
    # additional tools (Write/Bash) before emitting structured output
    # reliably causes the CLI to end with a text block instead of the
    # synthetic StructuredOutput tool_use — which then fails
    # StructuredOutput capture. Keeping the turn tool-free mirrors the
    # Phase 0 foundation smoke test.
    note_path_in_container = "/home/claude/.claude/CLAUDE.md"

    def _instructions() -> str:
        return (
            "# Role — Plan 2 headline probe\n\n"
            "You are a probe used by Agent Foundry's Plan 2 integration test. "
            "When asked, emit exactly the structured output the caller requests.\n"
        )

    def _prompt(s: StateA) -> str:
        return (
            f"Return structured output with headline='Archipelagos about {s.topic}' "
            f"and note_path='{note_path_in_container}'."
        )

    agent = AgentAction[StateA, StateB](
        name="researcher",
        prompt_builder=_prompt,
        instructions_provider=_instructions,
        executor=run_agent_in_container,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    )

    def _finalize(state: StateB, run_ctx: Any) -> StateC:
        # Emit a domain event so H.1 can assert the lifecycle_writer
        # pass-through into FunctionAction callables works end-to-end.
        run_ctx.lifecycle_writer.append_run_event(
            {
                "type": LifecycleEvent.DOMAIN.value,
                "kind": "plan2_h1_verification",
                "note_path": state.note_path,
            }
        )
        return StateC(headline=state.headline, verified=True)

    fn = FunctionAction[StateB, StateC](function=_finalize)
    seq = Sequence[StateA, StateC](steps=[agent, fn])
    plan = PrimitivePlan(root=seq)

    # The executor's default ``_run_claude_turn`` helper shells out to
    # the real ``claude`` CLI inside the live container. No test seam
    # needed — this end-to-end run exercises the production transport.

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    result = await run_primitive_plan(
        plan,
        initial_state=StateA(topic="archipelago"),
        artifacts_dir=artifacts_dir,
        workspace_volume=workspace_volume,
        base_image_tag=base_image,
        responder_provider=static_provider(_UnusedResponder()),
        run_id=run_id,
    )

    # --- Final state ------------------------------------------------------

    assert isinstance(result, StateC)
    assert result.verified is True
    assert result.headline.strip()

    run_dir = artifacts_dir / run_id
    assert run_dir.is_dir()

    # --- lifecycle.jsonl --------------------------------------------------

    jsonl = run_dir / "lifecycle.jsonl"
    assert jsonl.is_file()
    records = [json.loads(line) for line in jsonl.read_text().splitlines() if line.strip()]
    types = [r["type"] for r in records]

    expected_ordered = [
        LifecycleEvent.RUN_STARTED.value,
        LifecycleEvent.AGENT_CONTAINER_STARTED.value,
        LifecycleEvent.AGENT_INVOCATION_STARTED.value,
        LifecycleEvent.TURN_STARTED.value,
        LifecycleEvent.TURN_COMPLETED.value,
        LifecycleEvent.AGENT_INVOCATION_COMPLETED.value,
        LifecycleEvent.FUNCTION_ACTION_STARTED.value,
        LifecycleEvent.DOMAIN.value,
        LifecycleEvent.FUNCTION_ACTION_COMPLETED.value,
        LifecycleEvent.RUN_ENDED.value,
    ]
    # Each expected event appears at least once, and their relative
    # order is preserved.
    positions = []
    cursor = 0
    for needed in expected_ordered:
        found = None
        for i in range(cursor, len(types)):
            if types[i] == needed:
                found = i
                break
        assert found is not None, f"missing expected event {needed!r}; full sequence: {types}"
        positions.append(found)
        cursor = found + 1
    # Domain event carries the payload we sent.
    domain_records = [r for r in records if r["type"] == LifecycleEvent.DOMAIN.value]
    assert any(r.get("kind") == "plan2_h1_verification" for r in domain_records), (
        f"domain event payload missing expected kind: {domain_records}"
    )

    # --- Per-turn artifacts ----------------------------------------------

    agent_name = agent.name  # product-declared diagnostic label
    turn0 = run_dir / agent_name / "turns" / "0"
    assert turn0.is_dir(), f"expected turn dir {turn0}"
    assert (turn0 / "prompt.txt").is_file()
    assert (turn0 / "envelope.json").is_file()
    assert (turn0 / "output.json").is_file()
    collected = turn0 / "collected_files"
    assert collected.is_dir()
    # The snapshotted file has the container basename. ``extract_paths``
    # took the declared ``note_path`` field and the executor's
    # ``_snapshot_files`` copied to ``collected_files/<basename>``.
    snapshot_files = [p for p in collected.iterdir() if p.is_file()]
    assert snapshot_files, f"expected snapshot in {collected}, found: {list(collected.iterdir())}"
    assert any(p.name == Path(note_path_in_container).name for p in snapshot_files)

    # --- inspect-workspace.sh --------------------------------------------

    inspect = run_dir / "inspect-workspace.sh"
    assert inspect.is_file()
    assert os.access(inspect, os.X_OK), "inspect-workspace.sh should be executable"
    contents = inspect.read_text()
    assert workspace_volume in contents

    # --- summary.txt ------------------------------------------------------

    summary = run_dir / "summary.txt"
    assert summary.is_file()
    assert summary.read_text().strip(), "summary.txt should be non-empty"

    # --- No orphan containers (scoped to this run) -----------------------
    #
    # Scope the orphan check to containers that mounted this run's
    # workspace volume. Filtering by ``ancestor=base_image`` catches
    # sibling integration tests (e.g. the F0 test in
    # ``test_f0_agent_action_end_to_end.py``) that share the base image
    # and run in parallel under ``pdm test-integration``.
    residual = client.containers.list(all=True, filters={"volume": workspace_volume})
    assert not residual, (
        f"orphan containers remain for volume {workspace_volume}: {[c.name for c in residual]}"
    )
