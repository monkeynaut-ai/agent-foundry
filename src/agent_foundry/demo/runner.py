"""Decision Support demo runner."""

import json
from pathlib import Path
from typing import Any

from agent_foundry.compiler.compiler import compile_plan
from agent_foundry.observability.gates import (
    citation_validator_gate,
    evidence_first_gate,
    schema_validator_gate,
    uncertainty_completeness_gate,
)
from agent_foundry.planner.wiring_plan import GraphWiringPlan
from agent_foundry.registry.registry import RoleRegistry

PLAN_PATH = Path(__file__).parent / "decision_support_plan.json"

RECOMMENDATION_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "uncertainty": {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
                "rationale": {"type": "string"},
            },
            "required": ["confidence", "rationale"],
        },
    },
    "required": ["recommendation", "evidence_ids", "assumptions", "uncertainty"],
}


def _retriever_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Stub retriever that returns canned evidence."""
    query = state.get("question", "")
    evidence = [
        {"id": "e1", "text": f"Evidence about {query}", "source": "registry"},
        {"id": "e2", "text": "Supporting data point", "source": "docs"},
    ]
    return {**state, "retrieved_evidence": evidence}


def _structured_output_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Stub structured output that produces a recommendation."""
    evidence = state.get("retrieved_evidence", [])
    evidence_ids = [e["id"] for e in evidence]
    return {
        **state,
        "recommendation": {
            "recommendation": f"Based on analysis of {len(evidence)} evidence items",
            "evidence_ids": evidence_ids,
            "assumptions": ["Data is current", "Sources are reliable"],
            "uncertainty": {
                "confidence": 0.85,
                "rationale": "Strong evidence base with minor gaps",
            },
        },
    }


def _schema_gate_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Schema validator gate node."""
    rec = state.get("recommendation", {})
    result = schema_validator_gate(rec, RECOMMENDATION_SCHEMA)
    if not result["valid"]:
        return {**state, "gate_failure": "schema", "gate_errors": result["errors"]}
    return {**state, "schema_valid": True}


def _citation_gate_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Citation validator gate node."""
    rec = state.get("recommendation", {})
    evidence = state.get("retrieved_evidence", [])
    result = citation_validator_gate(
        evidence_ids=rec.get("evidence_ids", []),
        retrieved_evidence=evidence,
    )
    if not result["valid"]:
        return {**state, "gate_failure": "citation", "missing_ids": result["missing_ids"]}
    return {**state, "citations_valid": True}


def _uncertainty_gate_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Uncertainty completeness gate node."""
    rec = state.get("recommendation", {})
    result = uncertainty_completeness_gate(
        uncertainty=rec.get("uncertainty", {}),
    )
    if not result["valid"]:
        return {**state, "gate_failure": "uncertainty", "missing_fields": result["missing_fields"]}
    return {**state, "uncertainty_valid": True}


def _evidence_gate_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Evidence-first contract gate node."""
    evidence = state.get("retrieved_evidence", [])
    rec = state.get("recommendation", {})
    result = evidence_first_gate(
        retrieved_evidence=evidence,
        recommendation=rec,
    )
    if not result["valid"]:
        return {**state, "gate_failure": "evidence", "outcome": result["outcome"]}
    return {**state, "evidence_valid": True, "outcome": result["outcome"]}


def _tool_calling_handler(state: dict[str, Any]) -> dict[str, Any]:
    """Stub tool calling that executes a calculator."""
    question = state.get("question", "")
    if "calculate" in question.lower() or "math" in question.lower():
        tool_result = {"tool_name": "calculator", "args": {"expression": "2+2"}, "result": 4}
        return {**state, "tool_result": tool_result}
    return state


DEMO_HANDLERS = {
    "rag_retriever": _retriever_handler,
    "structured_output_pydantic": _structured_output_handler,
    "schema_validator": _schema_gate_handler,
    "citation_validator": _citation_gate_handler,
    "uncertainty_completeness_validator": _uncertainty_gate_handler,
    "evidence_first_contract": _evidence_gate_handler,
    "tool_calling": _tool_calling_handler,
}


def load_demo_plan() -> GraphWiringPlan:
    """Load the static Decision Support plan."""
    plan_data = json.loads(PLAN_PATH.read_text())
    return GraphWiringPlan(**plan_data)


def run_demo(
    question: str,
    domain: str = "general",
    constraints: list[str] | None = None,
    registry: RoleRegistry | None = None,
    plan: GraphWiringPlan | None = None,
) -> dict[str, Any]:
    """Run the Decision Support demo workflow.

    Args:
        question: The user question.
        domain: The domain context.
        constraints: Optional constraints.
        registry: Optional role registry (auto-loaded if None).
        plan: Optional plan (auto-loaded if None).

    Returns:
        The final state dict with recommendation and gate results.
    """
    if registry is None:
        registry = RoleRegistry.with_builtins()

    if plan is None:
        plan = load_demo_plan()

    graph = compile_plan(plan, registry, handler_registry=DEMO_HANDLERS)

    initial_state = {
        "question": question,
        "domain": domain,
        "constraints": constraints or [],
    }

    return graph.invoke(initial_state)
