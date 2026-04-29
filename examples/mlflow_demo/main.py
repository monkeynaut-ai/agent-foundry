"""End-to-end verification demo for MLflow tracing integration.

Wires a tiny AgentAction plan with a deterministic fake executor, configures
telemetry pointing at a local MLflow server, runs the plan, and exits.

Expects MLflow at http://localhost:5000 (see docker-compose.yaml). Reads
the experiment id from the env var ``AF_MLFLOW_EXPERIMENT_ID``.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from pydantic import BaseModel

from agent_foundry.mlflow_adapter import (
    MLFLOW_TRANSLATIONS,
)
from agent_foundry.mlflow_adapter import (
    enable as enable_mlflow_adapter,
)
from agent_foundry.orchestration.runner import run_primitive_plan
from agent_foundry.primitives.models import AgentAction, ContainerReusePolicy
from agent_foundry.primitives.plan import PrimitivePlan
from agent_foundry.telemetry import RunDefinition, TelemetryConfig


class TicketInput(BaseModel):
    ticket_id: str
    kind: str


class TicketOutput(BaseModel):
    success: bool
    summary: str


def fake_executor(
    *, primitive: AgentAction, prompt: str, instructions: str, run_ctx
) -> TicketOutput:
    return TicketOutput(success=True, summary=f"handled: {prompt[:60]}")


def build_plan() -> PrimitivePlan:
    action = AgentAction[TicketInput, TicketOutput](
        name="reviewer",
        prompt_builder=lambda inp: f"review ticket {inp.ticket_id} ({inp.kind})",
        instructions_provider=lambda _: "be terse, return TicketOutput",
        executor=fake_executor,
        reuse_policy=ContainerReusePolicy.REUSE_NEW_SESSION,
    )
    return PrimitivePlan(root=action)


MLFLOW_BASE_URL = os.environ.get("AF_MLFLOW_BASE_URL", "http://localhost:5000")
MLFLOW_EXPERIMENT_ID = os.environ.get("AF_MLFLOW_EXPERIMENT_ID", "0")


def build_telemetry() -> TelemetryConfig:
    return TelemetryConfig(
        otlp_endpoint=f"{MLFLOW_BASE_URL}/v1/traces",
        otlp_headers={"x-mlflow-experiment-id": MLFLOW_EXPERIMENT_ID},
        service_name="archipelago-demo",
        attribute_translations=MLFLOW_TRANSLATIONS,
        run_definition=RunDefinition(
            name=lambda inp: f"ticket-{inp.ticket_id}",
            params=lambda inp: {"ticket_id": inp.ticket_id, "kind": inp.kind},
            tags={"product": "archipelago", "env": "demo"},
            metrics=lambda out, stats: (
                {
                    "duration_ms": stats.duration_ms,
                    "success": float(out.success),
                }
                if out is not None
                else {"duration_ms": stats.duration_ms}
            ),
        ),
    )


async def main(run_id: str | None = None) -> TicketOutput:
    """Run the demo plan once and return the result.

    Accepts an optional ``run_id`` so the live smoke test can call ``main``
    multiple times with distinct IDs (each run bootstraps its own
    ``run_dir`` under ``artifacts_dir``, and ``bootstrap_run_artifacts``
    raises FileExistsError on collision).
    """
    import uuid

    resolved_run_id = run_id or f"demo-{uuid.uuid4().hex[:8]}"
    artifacts_dir = Path.cwd() / ".tmp" / "mlflow-demo"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    plan = build_plan()
    config = build_telemetry()
    input_model = TicketInput(ticket_id="42", kind="feature")

    def attach_adapter(event) -> None:
        enable_mlflow_adapter(
            config=config,
            run_context=event.run_context,
            input_model=input_model,
            tracking_uri=MLFLOW_BASE_URL,
            experiment_id=MLFLOW_EXPERIMENT_ID,
        )

    result = await run_primitive_plan(
        plan,
        initial_state=input_model,
        artifacts_dir=artifacts_dir,
        workspace_volume="archipelago-demo",
        base_image_tag="agent-worker:latest",
        responder_provider=lambda _id: lambda *a, **k: None,
        run_id=resolved_run_id,
        telemetry=config,
        on_run_starting=[attach_adapter],
    )

    print(f"Plan completed (run_id={resolved_run_id}). Result: {result!r}")
    print("Open http://localhost:5000 and look for run 'ticket-42'.")
    return result  # type: ignore[return-value]


if __name__ == "__main__":
    asyncio.run(main())
