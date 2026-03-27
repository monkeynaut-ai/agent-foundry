"""Plan validation functions for referential integrity and structural rules."""

from agent_foundry.planner.errors import (
    DanglingEdgeError,
    DuplicateNodeIdError,
    PlanValidationError,
    SchemaContractError,
    UnknownRoleError,
)
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import RoleRegistry

FF_PLAN_VALIDATION = True


def validate_plan(plan: GraphWiringPlan, registry: RoleRegistry) -> None:
    """Validate a wiring plan against a role registry.

    Checks: duplicate IDs, unknown roles, dangling edges,
    tool contracts, breakpoints, version coverage, loop termination.
    """
    if not FF_PLAN_VALIDATION:
        return

    _check_duplicate_node_ids(plan)
    _check_unknown_roles(plan, registry)
    _check_dangling_edges(plan)
    _check_tool_calling_contract(plan)
    _check_breakpoints(plan)
    _check_role_versions_coverage(plan)
    _check_loop_termination(plan)
    _check_node_io_against_state_schema(plan)
    _check_state_mapping_alignment(plan)


def _check_duplicate_node_ids(plan: GraphWiringPlan) -> None:
    seen: set[str] = set()
    for node in plan.nodes:
        if node.id in seen:
            raise DuplicateNodeIdError(
                message=f"Duplicate node id '{node.id}' in plan",
                node_id=node.id,
            )
        seen.add(node.id)


def _check_unknown_roles(plan: GraphWiringPlan, registry: RoleRegistry) -> None:
    for node in plan.nodes:
        if node.subgraph is not None:
            validate_plan(node.subgraph, registry)
            continue
        assert node.role is not None  # enforced by NodeDef validator
        if registry.get(node.role) is None:
            raise UnknownRoleError(
                message=f"Unknown role '{node.role}' in node '{node.id}'",
                role=node.role,
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
    has_tool_calling = any(n.role == "tool_calling" for n in plan.nodes if n.role is not None)
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


def _check_role_versions_coverage(plan: GraphWiringPlan) -> None:
    for node in plan.nodes:
        if node.subgraph is not None:
            continue
        if node.role not in plan.role_versions:
            raise PlanValidationError(
                f"Missing version entry for role '{node.role}' used by node '{node.id}'"
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


def _check_node_io_against_state_schema(plan: GraphWiringPlan) -> None:
    """Verify that node I/O keys are declared in the plan's state_schema."""
    if plan.state_schema is None:
        return
    allowed_keys = set(plan.state_schema.get("properties", {}).keys())

    for node in plan.nodes:
        if node.subgraph is not None:
            _check_node_io_against_state_schema(node.subgraph)
            continue

        if node.inputs_schema is not None:
            input_keys = set(node.inputs_schema.get("properties", {}).keys())
            undeclared = input_keys - allowed_keys
            if undeclared:
                raise SchemaContractError(
                    message=(
                        f"Node '{node.id}' declares input keys {undeclared} "
                        f"not found in state_schema"
                    ),
                    node_id=node.id,
                    undeclared_keys=undeclared,
                )

        if node.outputs_schema is not None:
            output_keys = set(node.outputs_schema.get("properties", {}).keys())
            undeclared = output_keys - allowed_keys
            if undeclared:
                raise SchemaContractError(
                    message=(
                        f"Node '{node.id}' declares output keys {undeclared} "
                        f"not found in state_schema"
                    ),
                    node_id=node.id,
                    undeclared_keys=undeclared,
                )


def _check_state_mapping_alignment(plan: GraphWiringPlan) -> None:
    """Verify that state_mapping keys align with parent and subgraph schemas."""
    if plan.state_schema is None:
        return
    parent_keys = set(plan.state_schema.get("properties", {}).keys())

    for node in plan.nodes:
        if node.subgraph is None or node.state_mapping is None:
            continue

        # Parent-side input keys must be in parent schema
        for parent_key in node.state_mapping.input:
            if parent_key not in parent_keys:
                raise SchemaContractError(
                    message=(
                        f"Node '{node.id}' state_mapping input references parent key "
                        f"'{parent_key}' not found in parent state_schema"
                    ),
                    node_id=node.id,
                    undeclared_keys={parent_key},
                )

        # Subgraph-side input values must be in subgraph schema (if declared)
        if node.subgraph.state_schema is not None:
            sub_keys = set(node.subgraph.state_schema.get("properties", {}).keys())

            for sub_key in node.state_mapping.input.values():
                if sub_key not in sub_keys:
                    raise SchemaContractError(
                        message=(
                            f"Node '{node.id}' state_mapping input maps to subgraph key "
                            f"'{sub_key}' not found in subgraph state_schema"
                        ),
                        node_id=node.id,
                        undeclared_keys={sub_key},
                    )

            for sub_key in node.state_mapping.output:
                if sub_key not in sub_keys:
                    raise SchemaContractError(
                        message=(
                            f"Node '{node.id}' state_mapping output references subgraph key "
                            f"'{sub_key}' not found in subgraph state_schema"
                        ),
                        node_id=node.id,
                        undeclared_keys={sub_key},
                    )

        # Parent-side output values must be in parent schema
        for parent_key in node.state_mapping.output.values():
            if parent_key not in parent_keys:
                raise SchemaContractError(
                    message=(
                        f"Node '{node.id}' state_mapping output maps to parent key "
                        f"'{parent_key}' not found in parent state_schema"
                    ),
                    node_id=node.id,
                    undeclared_keys={parent_key},
                )

        # Recurse into subgraph
        _check_state_mapping_alignment(node.subgraph)
