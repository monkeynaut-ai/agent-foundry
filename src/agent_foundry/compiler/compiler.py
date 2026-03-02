"""Plan compiler: converts GraphWiringPlan into executable LangGraph."""

import logging
from collections.abc import Callable
from typing import Any

from langgraph.graph import END, StateGraph

from agent_foundry.compiler.errors import (
    CapabilityInstantiationError,
    PlanCompilationError,
)
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.errors import CapabilityImportError
from agent_foundry.registry.execution import execute_capability
from agent_foundry.registry.imports import resolve_handler_callable
from agent_foundry.registry.registry import CapabilityRegistry
from agent_foundry.registry.spec import CapabilitySpec

logger = logging.getLogger(__name__)

FF_COMPILER = False


EVAL_GATE_CAPABILITIES = {
    "schema_validator", "citation_validator",
    "uncertainty_completeness_validator", "evidence_first_contract",
}


def compile_plan(
    plan: GraphWiringPlan,
    registry: CapabilityRegistry,
    handler_registry: dict[str, Any] | None = None,
    enforce_gates: bool = False,
) -> Any:
    """Compile a wiring plan into an executable LangGraph.

    Args:
        plan: The graph wiring plan.
        registry: The capability registry.
        handler_registry: Optional mapping of capability names to handler functions.

    Returns:
        A compiled LangGraph that can be invoked with state.

    Raises:
        PlanCompilationError: If the plan structure is invalid.
        CapabilityInstantiationError: If a handler cannot be resolved.
    """
    handler_registry = handler_registry or {}
    node_ids = {n.id for n in plan.nodes}

    # Validate entry point
    if plan.entry_point not in node_ids:
        raise PlanCompilationError(
            f"Entry point '{plan.entry_point}' not found in plan nodes: {node_ids}"
        )

    # Enforce eval gates on all paths if requested
    if enforce_gates:
        _check_eval_gates_on_paths(plan)

    graph = StateGraph(dict)

    # Determine graph topology
    source_nodes = {e.source for e in plan.edges}
    terminal_nodes = node_ids - source_nodes

    # Check for conditional edges
    has_conditional = any(e.condition is not None for e in plan.edges)

    # Check for loops (self-referencing or cycles)
    has_loops = any(e.target in source_nodes and e.target == e.source or
                    e.condition is not None for e in plan.edges
                    if e.source != e.target) or any(e.source == e.target for e in plan.edges)

    # Add nodes with loop-safe wrappers if needed
    for node in plan.nodes:
        handler = _resolve_handler(node.id, node.capability, handler_registry, registry)

        # Wrap with max_iterations if configured
        max_iter = node.config.get("max_iterations")
        if max_iter is not None:
            handler = _make_iteration_limiter(handler, node.id, max_iter)

        graph.add_node(node.id, handler)

    # Set entry point
    graph.set_entry_point(plan.entry_point)

    # Group edges by source
    edges_by_source: dict[str, list] = {}
    for edge in plan.edges:
        edges_by_source.setdefault(edge.source, []).append(edge)

    # Add edges
    for source_id, edges in edges_by_source.items():
        conditional_edges = [e for e in edges if e.condition is not None]
        unconditional_edges = [e for e in edges if e.condition is None]

        if conditional_edges:
            # Build a conditional routing function
            route_map: dict[str, str] = {}
            default_target = END

            for e in conditional_edges:
                route_map[e.condition] = e.target

            if unconditional_edges:
                default_target = unconditional_edges[0].target

            # Self-loops with conditions
            for e in conditional_edges:
                if e.source == e.target:
                    route_map[e.condition] = e.target

            router = _make_router(route_map, default_target, source_id)
            all_targets = {v for v in route_map.values()}
            all_targets.add(default_target)
            graph.add_conditional_edges(source_id, router, list(all_targets))
        else:
            for e in unconditional_edges:
                graph.add_edge(e.source, e.target)

    # Add edges to END for terminal nodes without outgoing edges
    for node_id in terminal_nodes:
        if node_id not in edges_by_source:
            graph.add_edge(node_id, END)

    # Single node with no edges
    if not plan.edges and len(plan.nodes) == 1:
        graph.add_edge(plan.entry_point, END)

    compile_kwargs: dict[str, Any] = {}

    if plan.persistence is not None:
        checkpointer = _create_checkpointer(plan.persistence.backend)
        compile_kwargs["checkpointer"] = checkpointer
        if plan.breakpoints:
            compile_kwargs["interrupt_before"] = plan.breakpoints

    return graph.compile(**compile_kwargs)


def _resolve_handler(
    node_id: str,
    capability: str,
    handler_registry: dict[str, Any],
    registry: CapabilityRegistry,
) -> Callable:
    # 1. Explicit handler_registry takes priority (backwards compat)
    handler = handler_registry.get(capability)
    if handler is not None:
        if not callable(handler):
            raise CapabilityInstantiationError(
                message=f"Handler for node '{node_id}' (capability '{capability}') is not callable",
                node_id=node_id,
                capability=capability,
            )
        return handler

    # 2. Fall back to dynamic resolution from registry spec
    spec = registry.get(capability)
    if spec is not None:
        try:
            resolved = resolve_handler_callable(spec.implementation, spec)
        except CapabilityImportError as e:
            raise CapabilityInstantiationError(
                message=f"Cannot resolve handler for node '{node_id}' (capability '{capability}'): {e}",
                node_id=node_id,
                capability=capability,
            ) from e

        if resolved is not None:
            return _make_validated_handler(resolved, spec)

    # 3. No handler found anywhere: passthrough
    logger.warning(
        "no_handler_found",
        extra={"node": node_id, "capability": capability},
    )
    return _make_passthrough(node_id)


def _make_validated_handler(
    handler: Callable, spec: CapabilitySpec,
) -> Callable:
    """Wrap a handler with execute_capability for schema enforcement."""
    def validated_handler(state: dict[str, Any]) -> dict[str, Any]:
        return execute_capability(spec, state, handler)
    return validated_handler


def _make_passthrough(node_id: str) -> Callable:
    def handler(state: dict[str, Any]) -> dict[str, Any]:
        return state
    return handler


def _make_iteration_limiter(
    handler: Callable, node_id: str, max_iterations: int
) -> Callable:
    counter = {"count": 0}

    def limited_handler(state: dict[str, Any]) -> dict[str, Any]:
        counter["count"] += 1
        result = handler(state)
        if counter["count"] >= max_iterations:
            # Signal to stop looping
            result["_loop_exhausted"] = True
        return result

    return limited_handler


def _make_router(
    route_map: dict[str, str], default_target: str, source_id: str
) -> Callable:
    def router(state: dict[str, Any]) -> str:
        # Check if loop is exhausted
        if state.get("_loop_exhausted"):
            logger.info("loop_exhausted", extra={"node": source_id})
            return END

        # Check conditions in deterministic order
        for condition, target in sorted(route_map.items()):
            if state.get(condition):
                logger.info(
                    "branch_taken",
                    extra={"node": source_id, "condition": condition, "target": target},
                )
                return target

        logger.info(
            "default_branch",
            extra={"node": source_id, "target": default_target},
        )
        return default_target

    return router


def _create_checkpointer(backend: str) -> Any:
    """Create a checkpointer for the given backend."""
    if backend == "memory":
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()
    raise PlanCompilationError(f"Unsupported persistence backend: {backend}")


def _check_eval_gates_on_paths(plan: GraphWiringPlan) -> None:
    """Ensure at least one eval gate is on every path from entry to terminal nodes."""
    node_capabilities = {n.id: n.capability for n in plan.nodes}
    gate_nodes = {n.id for n in plan.nodes if n.capability in EVAL_GATE_CAPABILITIES}

    if not gate_nodes:
        raise PlanCompilationError(
            "Plan has no eval gate nodes. At least one eval gate "
            f"({', '.join(sorted(EVAL_GATE_CAPABILITIES))}) must be on every path to final."
        )

    # Build adjacency
    adjacency: dict[str, list[str]] = {n.id: [] for n in plan.nodes}
    for edge in plan.edges:
        adjacency.setdefault(edge.source, []).append(edge.target)

    # Find terminal nodes
    source_nodes = {e.source for e in plan.edges}
    terminal_nodes = {n.id for n in plan.nodes} - source_nodes

    # DFS from entry_point to each terminal, check if any path lacks a gate
    def _has_gate_on_path(current: str, visited: set[str]) -> bool:
        if current in gate_nodes:
            return True
        if current in terminal_nodes and current not in gate_nodes:
            return False
        visited.add(current)
        neighbors = adjacency.get(current, [])
        if not neighbors:
            return current in gate_nodes
        return all(
            _has_gate_on_path(n, visited.copy())
            for n in neighbors if n not in visited
        )

    if not _has_gate_on_path(plan.entry_point, set()):
        raise PlanCompilationError(
            "Not all paths from entry to final pass through an eval gate."
        )
