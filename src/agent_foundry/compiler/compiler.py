"""Plan compiler: converts GraphWiringPlan into executable LangGraph."""

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, StateGraph

from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import CapabilityRegistry

FF_COMPILER = False


def compile_plan(
    plan: GraphWiringPlan,
    registry: CapabilityRegistry,
    handler_registry: dict[str, Callable] | None = None,
) -> Any:
    """Compile a wiring plan into an executable LangGraph.

    Args:
        plan: The graph wiring plan.
        registry: The capability registry.
        handler_registry: Optional mapping of capability names to handler functions.

    Returns:
        A compiled LangGraph that can be invoked with state.
    """
    handler_registry = handler_registry or {}

    # Build the state graph with a flexible dict state
    graph = StateGraph(dict)

    # Compute which nodes are targets of edges (to find terminal nodes)
    target_nodes = {e.target for e in plan.edges}
    source_nodes = {e.source for e in plan.edges}
    node_ids = {n.id for n in plan.nodes}
    terminal_nodes = node_ids - source_nodes

    # Add nodes
    for node in plan.nodes:
        handler = handler_registry.get(node.capability)
        if handler is None:
            handler = _make_passthrough(node.id)
        graph.add_node(node.id, handler)

    # Set entry point
    graph.set_entry_point(plan.entry_point)

    # Add edges
    for edge in plan.edges:
        graph.add_edge(edge.source, edge.target)

    # Add edges to END for terminal nodes
    for node_id in terminal_nodes:
        graph.add_edge(node_id, END)

    # If single node with no edges, connect to END
    if not plan.edges and len(plan.nodes) == 1:
        graph.add_edge(plan.entry_point, END)

    return graph.compile()


def _make_passthrough(node_id: str) -> Callable:
    """Create a passthrough handler that returns state unchanged."""
    def handler(state: dict[str, Any]) -> dict[str, Any]:
        return state
    return handler
