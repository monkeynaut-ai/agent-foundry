"""Deterministic architecture handler for the Archipelago pipeline."""

from agent_foundry.registry.spec import CapabilitySpec
from archipelago.models import FeatureArchitecture


class ArchitectureHandler:
    def __init__(self, spec: CapabilitySpec) -> None:
        self.spec = spec

    def __call__(self, state: dict) -> dict:
        brief = state.get("product_brief")
        if not brief:
            raise ValueError("product_brief is required")

        print(f"[architecture] Input: product_brief.name={brief['name']}")

        arch = FeatureArchitecture(
            feature_name=f"{brief['name'][:40]} Core",
            components=["API Gateway", "Core Service", "Data Layer", "Auth Module"],
            data_flow="Client -> API Gateway -> Core Service -> Data Layer",
            technology_choices=["Python", "FastAPI", "PostgreSQL", "Redis"],
            risks=["Schema migration complexity", "Third-party API rate limits"],
        )

        print(f"[architecture] Generated feature architecture: {arch.feature_name}")
        return {**state, "feature_architecture": arch.model_dump()}
