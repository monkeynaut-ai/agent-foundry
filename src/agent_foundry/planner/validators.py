"""Plan validation functions for referential integrity and structural rules."""

from agent_foundry.planner.errors import (
    DanglingEdgeError,
    DuplicateNodeIdError,
    PlanValidationError,
    UnknownCapabilityError,
)
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import CapabilityRegistry

FF_PLAN_VALIDATION = True


def validate_plan(plan: GraphWiringPlan, registry: CapabilityRegistry) -> None:
    """Validate a wiring plan against a capability registry.

    Checks: duplicate IDs, unknown capabilities, dangling edges,
    tool contracts, breakpoints, version coverage, loop termination.
    """
    if not FF_PLAN_VALIDATION:
        return

    _check_duplicate_node_ids(plan)
    _check_unknown_capabilities(plan, registry)
    _check_dangling_edges(plan)
    _check_tool_calling_contract(plan)
    _check_breakpoints(plan)
    _check_capability_versions_coverage(plan)
    _check_loop_termination(plan)


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


def _check_tool_calling_contract(plan: GraphWiringPlan) -> None:
    has_tool_calling = any(n.capability == "tool_calling" for n in plan.nodes)
    if not has_tool_calling:
        return

    if not plan.tools:
        raise PlanValidationError("Plan has tool_calling node but no tools defined")

    tool_names: set[str] = set()
    for tool in plan.tools:
        if tool.name in tool_names:
            raise PlanValidationError(f"duplicate tool name '{tool.name}' in plan tools list")
        tool_names.add(tool.name)


def _check_breakpoints(plan: GraphWiringPlan) -> None:
    node_ids = {node.id for node in plan.nodes}
    for bp in plan.breakpoints:
        if bp not in node_ids:
            raise PlanValidationError(f"breakpoint references non-existent node '{bp}'")


def _check_capability_versions_coverage(plan: GraphWiringPlan) -> None:
    for node in plan.nodes:
        if node.capability not in plan.capability_versions:
            raise PlanValidationError(
                f"Missing version entry for capability '{node.capability}' used by node '{node.id}'"
            )


def _check_loop_termination(plan: GraphWiringPlan) -> None:
    """Detect cycles and require termination conditions or max_iterations."""
    adjacency: dict[str, list[str]] = {}
    conditional_edges: set[tuple[str, str]] = set()

    for edge in plan.edges:
        adjacency.setdefault(edge.source, []).append(edge.target)
        if edge.condition is not None:
            conditional_edges.add((edge.source, edge.target))

    node_configs = {n.id: n.config for n in plan.nodes}

    # DFS cycle detection
    visited: set[str] = set()
    rec_stack: set[str] = set()
    cycle_nodes: list[str] = []

    def _dfs(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                if _dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                cycle_nodes.append(neighbor)
                return True
        rec_stack.discard(node)
        return False

    for node_id in {n.id for n in plan.nodes}:
        if node_id not in visited and _dfs(node_id):
            break

    if not cycle_nodes:
        return

    # Cycle found — check if all back-edges have conditions or nodes have max_iterations
    for edge in plan.edges:
        is_back_edge = edge.target in cycle_nodes or edge.source in cycle_nodes
        if not is_back_edge:
            continue
        if (edge.source, edge.target) in conditional_edges:
            continue
        # Check if source node has max_iterations config
        config = node_configs.get(edge.source, {})
        if config.get("max_iterations") is not None:
            continue
        raise PlanValidationError(
            f"cycle detected involving node '{cycle_nodes[0]}'"
            " without termination condition or max_iterations"
        )
