"""Archipelago pipeline runner."""

import json
from pathlib import Path
from typing import Any

from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import CapabilityRegistry
from archipelago.docker_worker.handler import docker_worker_handler
from archipelago.docker_worker.models import WorkerConstraints, WorkerInput
from archipelago.handlers import ARCHIPELAGO_HANDLERS

PLAN_PATH = Path(__file__).parent / "archipelago_system.json"


def load_archipelago_plan() -> GraphWiringPlan:
    """Load the static Archipelago pipeline plan."""
    plan_data = json.loads(PLAN_PATH.read_text())
    return GraphWiringPlan(**plan_data)


def run_archipelago(
    product_brief_input: str,
    registry: CapabilityRegistry | None = None,
    plan: GraphWiringPlan | None = None,
) -> dict[str, Any]:
    """Run the Archipelago pipeline end-to-end.

    Args:
        product_brief_input: High-level product idea text.
        registry: Optional capability registry (auto-loaded if None).
        plan: Optional plan (auto-loaded if None).

    Returns:
        The final state dict with all pipeline artifacts.
    """
    if registry is None:
        registry = CapabilityRegistry.with_product_specs(Path(__file__).parent / "capabilities")

    if plan is None:
        plan = load_archipelago_plan()

    graph = compile_plan(plan, registry, handler_registry=ARCHIPELAGO_HANDLERS)

    initial_state = {"product_brief_input": product_brief_input}
    return graph.invoke(initial_state)


def run_dev_test(dev_test_input: dict[str, Any]) -> dict[str, Any]:
    """Bypass the full pipeline and run only the dev_test worker directly."""
    worker_input = WorkerInput(
        repo_url=dev_test_input.get("repo_url"),
        repo_ref=dev_test_input.get("repo_ref", "main"),
        feature_spec=dev_test_input.get("feature_spec", {}),
        test_commands=dev_test_input.get("test_commands", ["pdm run pytest"]),
        gates=dev_test_input.get("gates", []),
        constraints=WorkerConstraints(**dev_test_input.get("constraints", {})),
    )
    return docker_worker_handler({"worker_input": worker_input.model_dump()})
