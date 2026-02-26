"""Wiring planner: deterministic plan generation from goals."""

from agent_foundry.planner.wiring_plan import GraphWiringPlan, NodeDef, EdgeDef
from agent_foundry.registry.registry import CapabilityRegistry

FF_PLANNER = False

# Deterministic goal-to-plan mappings
_DECISION_SUPPORT_PLAN = {
    "goal": "decision-support",
    "nodes": [
        {"id": "retriever", "capability": "rag_retriever", "config": {}},
        {"id": "output", "capability": "structured_output_pydantic", "config": {}},
        {"id": "schema_gate", "capability": "schema_validator", "config": {}},
        {"id": "citation_gate", "capability": "citation_validator", "config": {}},
        {"id": "uncertainty_gate", "capability": "uncertainty_completeness_validator", "config": {}},
        {"id": "evidence_gate", "capability": "evidence_first_contract", "config": {}},
    ],
    "edges": [
        {"source": "retriever", "target": "output"},
        {"source": "output", "target": "schema_gate"},
        {"source": "schema_gate", "target": "citation_gate"},
        {"source": "citation_gate", "target": "uncertainty_gate"},
        {"source": "uncertainty_gate", "target": "evidence_gate"},
    ],
    "entry_point": "retriever",
    "capability_versions": {
        "rag_retriever": "1.0.0",
        "structured_output_pydantic": "1.0.0",
        "schema_validator": "1.0.0",
        "citation_validator": "1.0.0",
        "uncertainty_completeness_validator": "1.0.0",
        "evidence_first_contract": "1.0.0",
    },
}

_GOAL_PLANS: dict[str, dict] = {
    "decision-support": _DECISION_SUPPORT_PLAN,
}


class WiringPlanner:
    """Deterministic planner that selects capabilities from the registry."""

    def __init__(self, registry: CapabilityRegistry, snippets: list | None = None):
        self._registry = registry
        self._snippets = snippets or []

    def plan(self, goal: str) -> GraphWiringPlan:
        """Generate a wiring plan for the given goal.

        Args:
            goal: The planning goal (e.g., "decision-support").

        Returns:
            A valid GraphWiringPlan.

        Raises:
            ValueError: If no plan template exists for the goal.
        """
        if goal in _GOAL_PLANS:
            plan_data = _GOAL_PLANS[goal].copy()
        else:
            plan_data = self._build_minimal_plan(goal)

        return GraphWiringPlan(**plan_data)

    def _build_minimal_plan(self, goal: str) -> dict:
        """Build a minimal plan with the first available capability."""
        names = self._registry.names()
        if not names:
            raise ValueError(f"No capabilities available for goal '{goal}'")
        first = names[0]
        spec = self._registry.get(first)
        return {
            "goal": goal,
            "nodes": [{"id": "node_0", "capability": first, "config": {}}],
            "edges": [],
            "entry_point": "node_0",
            "capability_versions": {first: spec.version if spec else "0.0.0"},
        }
