"""Wiring planner: deterministic plan generation from goals."""

import concurrent.futures
from typing import Any

from langchain_core.documents import Document

from agent_foundry.planner.errors import (
    PlanningInsufficientContextError,
    PlanningTimeoutError,
)
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import CapabilityRegistry

FF_PLANNER = False

# Deterministic goal-to-plan mappings
_DECISION_SUPPORT_PLAN: dict[str, Any] = {
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

_DECISION_SUPPORT_WITH_TOOLS_PLAN: dict[str, Any] = {
    **_DECISION_SUPPORT_PLAN,
    "goal": "decision-support-with-tools",
    "nodes": [
        {"id": "retriever", "capability": "rag_retriever", "config": {}},
        {"id": "tools", "capability": "tool_calling", "config": {}},
        {"id": "output", "capability": "structured_output_pydantic", "config": {}},
        {"id": "schema_gate", "capability": "schema_validator", "config": {}},
        {"id": "citation_gate", "capability": "citation_validator", "config": {}},
        {"id": "uncertainty_gate", "capability": "uncertainty_completeness_validator", "config": {}},
        {"id": "evidence_gate", "capability": "evidence_first_contract", "config": {}},
    ],
    "edges": [
        {"source": "retriever", "target": "tools"},
        {"source": "tools", "target": "output"},
        {"source": "output", "target": "schema_gate"},
        {"source": "schema_gate", "target": "citation_gate"},
        {"source": "citation_gate", "target": "uncertainty_gate"},
        {"source": "uncertainty_gate", "target": "evidence_gate"},
    ],
    "entry_point": "retriever",
    "tools": [
        {"name": "calculator", "args_schema": {"type": "object", "properties": {"expression": {"type": "string"}}}},
    ],
    "capability_versions": {
        **_DECISION_SUPPORT_PLAN["capability_versions"],
        "tool_calling": "1.0.0",
    },
}

_ARCHIPELAGO_PIPELINE_PLAN: dict[str, Any] = {
    "goal": "archipelago-pipeline",
    "nodes": [
        {"id": "strategy", "capability": "strategy_generate_product_brief", "config": {}},
        {"id": "architecture", "capability": "architecture_generate_feature_arch", "config": {}},
        {"id": "spec", "capability": "spec_generate_feature_spec", "config": {}},
        {"id": "spec_approval_gate", "capability": "human_approval_gate", "config": {}},
        {"id": "dev_test", "capability": "coding_implement_feature_from_spec", "config": {}},
    ],
    "edges": [
        {"source": "strategy", "target": "architecture"},
        {"source": "architecture", "target": "spec"},
        {"source": "spec", "target": "spec_approval_gate"},
        {"source": "spec_approval_gate", "target": "dev_test"},
    ],
    "entry_point": "strategy",
    "breakpoints": ["spec_approval_gate"],
    "capability_versions": {
        "strategy_generate_product_brief": "1.0.0",
        "architecture_generate_feature_arch": "1.0.0",
        "spec_generate_feature_spec": "1.0.0",
        "human_approval_gate": "1.0.0",
        "coding_implement_feature_from_spec": "1.0.0",
    },
}

_GOAL_PLANS: dict[str, dict] = {
    "decision-support": _DECISION_SUPPORT_PLAN,
    "decision-support-with-tools": _DECISION_SUPPORT_WITH_TOOLS_PLAN,
    "archipelago-pipeline": _ARCHIPELAGO_PIPELINE_PLAN,
}


class WiringPlanner:
    """Deterministic planner that selects capabilities from the registry."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        snippets: list[Document] | None = None,
        strict: bool = False,
        timeout_seconds: float | None = None,
    ):
        self._registry = registry
        self._snippets = snippets or []
        self._strict = strict
        self._timeout_seconds = timeout_seconds

    def plan(self, goal: str, risk: str = "low") -> GraphWiringPlan:
        """Generate a wiring plan for the given goal.

        Args:
            goal: The planning goal.
            risk: Risk level ("low", "medium", "high").

        Returns:
            A valid GraphWiringPlan.
        """
        if self._timeout_seconds is not None:
            return self._plan_with_timeout(goal, risk)
        return self._generate_plan(goal, risk)

    def _plan_with_timeout(self, goal: str, risk: str) -> GraphWiringPlan:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._generate_plan, goal, risk)
            try:
                return future.result(timeout=self._timeout_seconds)
            except concurrent.futures.TimeoutError:
                raise PlanningTimeoutError(
                    f"Planning for goal '{goal}' timed out after {self._timeout_seconds}s"
                )

    def _generate_plan(self, goal: str, risk: str) -> GraphWiringPlan:
        # Strict mode: require snippets for unknown goals
        if self._strict and not self._snippets and goal not in _GOAL_PLANS:
            raise PlanningInsufficientContextError(
                f"No snippets available for goal '{goal}' in strict mode"
            )

        if goal in _GOAL_PLANS:
            import copy
            plan_data = copy.deepcopy(_GOAL_PLANS[goal])
        else:
            plan_data = self._build_minimal_plan(goal)

        # Apply HITL breakpoint for high-risk tool plans
        if risk == "high" and self._has_tool_calling(plan_data):
            tool_node_ids = [
                n["id"] for n in plan_data["nodes"]
                if n["capability"] == "tool_calling"
            ]
            plan_data["breakpoints"] = tool_node_ids
            # Add human_approval_gate node if not present
            if not any(n["capability"] == "human_approval_gate" for n in plan_data["nodes"]):
                plan_data["nodes"].append({
                    "id": "human_gate",
                    "capability": "human_approval_gate",
                    "config": {},
                })
                plan_data["capability_versions"]["human_approval_gate"] = "1.0.0"

        return GraphWiringPlan(**plan_data)

    def _has_tool_calling(self, plan_data: dict) -> bool:
        return any(n["capability"] == "tool_calling" for n in plan_data.get("nodes", []))

    def _build_minimal_plan(self, goal: str) -> dict:
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
