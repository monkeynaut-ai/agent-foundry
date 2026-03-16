"""Deterministic strategy handler for the Archipelago pipeline."""

from agent_foundry.registry.spec import RoleSpec
from archipelago.models import ProductBrief


class StrategyHandler:
    def __init__(self, spec: RoleSpec) -> None:
        self.spec = spec

    def __call__(self, state: dict) -> dict:
        product_brief_input = state.get("product_brief_input", "")
        if not product_brief_input:
            raise ValueError("product_brief_input is required")

        brief = ProductBrief(
            name=f"Product: {product_brief_input[:50]}",
            problem_statement=f"Users need a solution for: {product_brief_input}",
            target_personas=["Developer", "Product Manager", "End User"],
            success_metrics=[
                "User adoption rate",
                "Task completion time",
                "User satisfaction score",
            ],
            constraints=["Must integrate with existing systems", "Budget-conscious deployment"],
        )

        print(f"[strategy] Generated product brief: {brief.name}")
        return {**state, "product_brief": brief.model_dump()}
