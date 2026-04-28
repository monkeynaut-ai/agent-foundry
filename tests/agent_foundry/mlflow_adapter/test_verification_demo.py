"""Live smoke test: runs the demo against a real local MLflow.

Skipped unless ``AF_LIVE_MLFLOW=1`` is set in the environment. Use:

    docker compose -f examples/mlflow_demo/docker-compose.yaml up -d
    export AF_LIVE_MLFLOW=1
    export AF_MLFLOW_EXPERIMENT_ID=<id>
    pdm test-all -k verification_demo
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AF_LIVE_MLFLOW") != "1",
    reason="Live MLflow required (set AF_LIVE_MLFLOW=1)",
)


@pytest.mark.integration
def test_verification_demo_run_appears_in_mlflow() -> None:
    import uuid

    from examples.mlflow_demo.main import main
    from mlflow.tracking import MlflowClient

    run_id = f"smoke-run-{uuid.uuid4().hex[:8]}"
    asyncio.run(main(run_id=run_id))

    experiment_id = os.environ["AF_MLFLOW_EXPERIMENT_ID"]
    client = MlflowClient(tracking_uri="http://localhost:5000")
    runs = client.search_runs(
        experiment_ids=[experiment_id],
        filter_string="tags.mlflow.runName = 'ticket-42'",
        max_results=10,
    )

    assert len(runs) >= 1, "Expected at least one run named ticket-42"
    run = runs[0]
    assert run.data.params["ticket_id"] == "42"
    assert run.data.params["kind"] == "feature"
    assert run.data.tags.get("product") == "archipelago"
    assert "duration_ms" in run.data.metrics


@pytest.mark.integration
def test_verification_demo_trace_carries_both_namespaces() -> None:
    import uuid

    import mlflow
    from examples.mlflow_demo.main import main

    run_id = f"smoke-trace-{uuid.uuid4().hex[:8]}"
    asyncio.run(main(run_id=run_id))

    experiment_id = os.environ["AF_MLFLOW_EXPERIMENT_ID"]
    traces = mlflow.search_traces(experiment_ids=[experiment_id], max_results=10)
    assert len(traces) >= 1, "Expected at least one trace"
    spans = traces.iloc[0].spans
    assert len(spans) >= 1
    span = spans[0]
    attrs = span.attributes
    assert "agent_foundry.input" in attrs
    assert "mlflow.spanInputs" in attrs
    assert attrs.get("gen_ai.operation.name") == "chat"
