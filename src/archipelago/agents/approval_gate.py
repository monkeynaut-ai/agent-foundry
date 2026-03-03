"""Deterministic approval gate handler for the Archipelago pipeline."""

from agent_foundry.registry.spec import CapabilitySpec


class ApprovalGateHandler:
    def __init__(self, spec: CapabilitySpec) -> None:
        self.spec = spec

    def __call__(self, state: dict) -> dict:
        feature_spec = state.get("feature_spec", {})
        title = feature_spec.get("title", "unknown")
        print(f"[approval_gate] Input: feature_spec.title={title}")
        print("[approval_gate] Auto-approved")
        return {**state, "approved": True, "approver": "auto"}
