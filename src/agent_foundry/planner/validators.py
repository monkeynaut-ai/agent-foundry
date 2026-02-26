"""Plan validation functions for referential integrity and structural rules."""

from agent_foundry.planner.errors import (
    DanglingEdgeError,
    DuplicateNodeIdError,
    UnknownCapabilityError,
)
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import CapabilityRegistry

FF_PLAN_VALIDATION = True


def validate_plan(plan: GraphWiringPlan, registry: CapabilityRegistry) -> None:
    """Validate a wiring plan against a capability registry.

    Checks: unknown capabilities, duplicate node IDs, dangling edges.

    Args:
        plan: The graph wiring plan to validate.
        registry: The capability registry to check against.

    Raises:
        UnknownCapabilityError: If a node references an unknown capability.
        DuplicateNodeIdError: If two nodes share the same ID.
        DanglingEdgeError: If an edge references a non-existent node.
    """
    if not FF_PLAN_VALIDATION:
        return

    _check_duplicate_node_ids(plan)
    _check_unknown_capabilities(plan, registry)
    _check_dangling_edges(plan)


def _check_duplicate_node_ids(plan: GraphWiringPlan) -> None:
    seen: set[str] = set()
    for node in plan.nodes:
        if node.id in seen:
            raise DuplicateNodeIdError(
                message=f"Duplicate node id '{node.id}' in plan",
                node_id=node.id,
            )
        seen.add(node.id)


def _check_unknown_capabilities(plan: GraphWiringPlan, registry: CapabilityRegistry) -> None:
    for node in plan.nodes:
        if registry.get(node.capability) is None:
            raise UnknownCapabilityError(
                message=f"Unknown capability '{node.capability}' in node '{node.id}'",
                capability=node.capability,
                node_id=node.id,
            )


def _check_dangling_edges(plan: GraphWiringPlan) -> None:
    node_ids = {node.id for node in plan.nodes}
    for edge in plan.edges:
        if edge.source not in node_ids:
            raise DanglingEdgeError(
                message=f"Edge source '{edge.source}' not found in nodes",
                node_id=edge.source,
            )
        if edge.target not in node_ids:
            raise DanglingEdgeError(
                message=f"Edge target '{edge.target}' not found in nodes",
                node_id=edge.target,
            )
